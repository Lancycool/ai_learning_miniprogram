"""A single durable private-document worker; no connection held during processing."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
import logging

from sqlalchemy import select, update

from app.core.knowledge_errors import KnowledgeError
from app.db.base import utc_now
from app.db.models import KnowledgeBase, KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeProcessingTask, QuestionBank, User
from app.services.auth_service import public_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowledgeClaim:
    task_id: int
    public_id: str
    user_id: int
    document_id: int
    version_id: int
    token: str
    task_type: str
    payload: dict
    source_key: str
    parsed_key: str | None
    file_type: str
    document_public_id: str
    version_public_id: str


class KnowledgeTaskWorker:
    def __init__(self, sessions, settings, *, processor=None):
        self.sessions, self.settings = sessions, settings
        if processor is None:
            from app.services.knowledge_processing_service import KnowledgeProcessor
            processor = KnowledgeProcessor(sessions, settings)
        self.processor = processor
        self.runner = None

    def start(self):
        if self.runner is None:
            self.runner = asyncio.create_task(self._loop(), name="knowledge-worker")

    async def close(self):
        if self.runner is not None:
            self.runner.cancel()
            with suppress(asyncio.CancelledError):
                await self.runner
            self.runner = None

    async def _loop(self):
        while True:
            try:
                if await self.run_once():
                    continue
            except Exception as exc:
                logger.warning("knowledge_worker_error type=%s", type(exc).__name__)
            await asyncio.sleep(self.settings.knowledge_task_poll_seconds)

    async def expire_stale(self):
        now = utc_now()
        async with self.sessions() as db, db.begin():
            await db.execute(update(KnowledgeProcessingTask).where(
                KnowledgeProcessingTask.status == "running", KnowledgeProcessingTask.lease_expires_at <= now
            ).values(status="failed", error_code="worker_interrupted", error_message="资料处理已中断，请重试",
                     completed_at=now, claim_token=None, lease_expires_at=None))
            await db.execute(update(KnowledgeProcessingTask).where(
                KnowledgeProcessingTask.status == "queued",
                KnowledgeProcessingTask.created_at <= now-timedelta(seconds=self.settings.knowledge_task_queue_timeout_seconds)
            ).values(status="failed", error_code="queue_timeout", error_message="资料排队超时，请重试", completed_at=now))

    async def claim(self):
        async with self.sessions() as db, db.begin():
            task = await db.scalar(select(KnowledgeProcessingTask).where(KnowledgeProcessingTask.status == "queued")
                .order_by(KnowledgeProcessingTask.created_at, KnowledgeProcessingTask.id).limit(1).with_for_update(skip_locked=True))
            if task is None:
                return None
            doc = await db.get(KnowledgeDocument, task.document_id)
            version = await db.get(KnowledgeDocumentVersion, task.version_id)
            base = await db.get(KnowledgeBase, task.knowledge_base_id)
            user = await db.get(User, task.user_id)
            bank = await db.scalar(select(QuestionBank).where(QuestionBank.public_id == task.request_json.get("bank_id"),
                QuestionBank.user_id == task.user_id, QuestionBank.document_id == task.document_id,
                QuestionBank.version_id == task.version_id)) if task.task_type == "original_practice" else None
            allowed = bool(doc and version and base and user and user.status == "active"
                and doc.user_id == version.user_id == base.user_id == user.id
                and version.document_id == doc.id and doc.knowledge_base_id == base.id
                and (task.task_type == "cleanup" or (doc.deleted_at is None and base.deleted_at is None
                                                     and (doc.current_version_id == version.id or bank is not None))))
            if not allowed:
                task.status, task.error_code, task.error_message = "failed", "source_changed", "资料已删除或版本已变化"
                task.completed_at = utc_now()
                return None
            task.status, task.stage = "running", "starting"
            task.claim_token, task.started_at = public_id("claim"), utc_now()
            task.lease_expires_at = task.started_at+timedelta(seconds=self.settings.knowledge_task_timeout_seconds+15)
            return KnowledgeClaim(task.id, task.public_id, task.user_id, doc.id, version.id, task.claim_token,
                task.task_type, task.request_json, version.source_key, version.parsed_key, doc.file_type,
                doc.public_id, version.public_id)

    async def current(self, db, claim):
        user = await db.scalar(select(User).where(User.id == claim.user_id).with_for_update())
        # The document precedes the task lock, matching deletion and version edits.
        doc = await db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.id == claim.document_id,
             KnowledgeDocument.user_id == claim.user_id).with_for_update())
        task = await db.scalar(select(KnowledgeProcessingTask).where(
            KnowledgeProcessingTask.id == claim.task_id, KnowledgeProcessingTask.user_id == claim.user_id,
            KnowledgeProcessingTask.status == "running", KnowledgeProcessingTask.claim_token == claim.token,
            KnowledgeProcessingTask.lease_expires_at > utc_now()).with_for_update())
        if task is None:
            return None
        if not user or user.status != "active":
            raise KnowledgeError("source_changed", "当前账号无法使用资料任务", 404)
        if claim.task_type != "cleanup":
            base = await db.get(KnowledgeBase, doc.knowledge_base_id) if doc else None
            historical_practice = claim.task_type == "original_practice" and await db.scalar(select(QuestionBank.id).where(
                QuestionBank.public_id == claim.payload.get("bank_id"), QuestionBank.user_id == claim.user_id,
                QuestionBank.document_id == claim.document_id, QuestionBank.version_id == claim.version_id))
            if not doc or doc.deleted_at or (doc.current_version_id != claim.version_id and not historical_practice) or not base or base.deleted_at:
                raise KnowledgeError("source_changed", "资料已删除或版本已变化", 409)
        return task

    async def progress(self, claim, stage, count=0, total=None):
        async with self.sessions() as db, db.begin():
            task = await self.current(db, claim)
            if task is None:
                raise KnowledgeError("source_changed", "资料任务已结束", 409)
            task.stage, task.processed_count, task.total_count = stage, count, total

    async def run_once(self):
        await self.expire_stale()
        claim = await self.claim()
        if claim is None:
            return False
        await self.execute(claim)
        return True

    async def execute(self, claim):
        result, published = None, False
        try:
            async with asyncio.timeout(self.settings.knowledge_task_timeout_seconds):
                result = await self.processor.process(claim, lambda *args: self.progress(claim, *args))
                async with self.sessions() as db, db.begin():
                    task = await self.current(db, claim)
                    if task is None:
                        return
                    task.result_json = await self.processor.publish(db, claim, result)
                    task.status, task.stage, task.completed_at = "succeeded", "complete", utc_now()
                    task.claim_token, task.lease_expires_at = None, None
                published = True
        except asyncio.CancelledError:
            await self.fail(claim, "worker_interrupted", "资料处理已中断，请重试")
            raise
        except TimeoutError:
            await self.fail(claim, "task_timeout", "资料处理超时，请拆分资料或重试")
        except Exception as exc:
            logger.warning("knowledge_task_failed task_id=%s type=%s", claim.public_id, type(exc).__name__)
            reason = exc.reason if isinstance(exc, KnowledgeError) else "processing_failed"
            message = exc.public_message if isinstance(exc, KnowledgeError) else "资料处理失败，请检查文件后重试"
            await self.fail(claim, reason, message)
        finally:
            cleanup = getattr(self.processor, "discard", None)
            if cleanup and not published:
                try:
                    await cleanup(claim, result)
                except Exception as exc:
                    logger.warning("knowledge_discard_failed task_id=%s type=%s", claim.public_id, type(exc).__name__)

    async def fail(self, claim, code, message):
        async with self.sessions() as db, db.begin():
            task = await db.scalar(select(KnowledgeProcessingTask).where(
                KnowledgeProcessingTask.id == claim.task_id, KnowledgeProcessingTask.status == "running",
                KnowledgeProcessingTask.claim_token == claim.token).with_for_update())
            if task is None:
                return
            task.status, task.error_code, task.error_message = "failed", code, message
            task.completed_at, task.claim_token, task.lease_expires_at = utc_now(), None, None
            doc = await db.get(KnowledgeDocument, claim.document_id)
            if doc and claim.task_type == "cleanup":
                doc.cleanup_status = "failed"
            if doc and doc.current_version_id == claim.version_id and not doc.deleted_at:
                if claim.task_type == "parse_index":
                    if doc.parse_status != "ready":
                        doc.parse_status = "failed"
                    doc.index_status = "failed"
