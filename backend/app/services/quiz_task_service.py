"""Durable database queue. Model calls never hold a database connection."""
import asyncio
import logging
from time import monotonic
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.knowledge_errors import KnowledgeError
from app.core.exceptions import AppError, ConflictError, ResourceNotFoundError
from app.db.base import utc_now
from app.db.models import LearningAttempt, Question, Quiz, QuizGenerationTask, User
from app.models.quiz import QuizGenerateRequest
from app.models.quiz_task import QuizTaskCreateRequest
from app.models.web_search import search_view
from app.services.auth_service import public_id
from app.services.learning_service import LearningService, question_view
from app.services.quiz_persistence import save_generated_quiz
from app.services.quiz_service import QuizGenerator, QuizService
from app.services.web_search_service import WebSearchService
from app.services.knowledge_trace_service import persist_trace
from app.utils.content_filter import ContentFilter
from app.core.observability import (
    record_task_created,
    record_task_finished,
    record_task_queue_wait,
    request_id_context,
    task_context,
)


logger = logging.getLogger(__name__)
ACTIVE_STATUSES = ("queued", "running")
TASK_POLL_AFTER_MS = 5000


def log_failure(event: str, exc: Exception, task_id: str = "") -> None:
    try:
        logger.warning("%s task_id=%s type=%s", event, task_id, type(exc).__name__)
    except Exception:
        pass


class QuizTaskService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db, self.settings = db, settings

    async def create(self, user: User, request: QuizTaskCreateRequest) -> dict:
        created = False
        payload = request.model_dump(mode="json", exclude={"request_id", "knowledge_scope", "public_search_topic", "public_search_confirmed"})
        payload["user_input"] = ContentFilter(self.settings.blocked_term_list).clean(request.user_input)
        # Serialize submissions for this user, including requests from two devices.
        await self.db.scalar(select(User.id).where(User.id == user.id).with_for_update())
        if request.knowledge_scope is not None:
            from app.services.knowledge_service import KnowledgeService
            from app.services.knowledge_quiz_service import KnowledgeQuizService
            scope = request.knowledge_scope.model_dump(mode="json")
            scope["documents"] = sorted(scope["documents"], key=lambda d: d["document_id"])
            for document in scope["documents"]:
                if document["chapter_ids"] is not None:
                    document["chapter_ids"] = sorted(set(document["chapter_ids"]))
            payload.update(knowledge_scope=scope, public_search_topic=request.public_search_topic,
                           public_search_confirmed=request.public_search_confirmed)
        task = await self.db.scalar(select(QuizGenerationTask).where(QuizGenerationTask.user_id == user.id, QuizGenerationTask.request_id == request.request_id).with_for_update())
        if task:
            if task.request_json != payload:
                raise ConflictError("同一请求编号不能用于不同的学习内容")
        else:
            if request.knowledge_scope is not None:
                await KnowledgeService(self.db, self.settings).resolve_scope(user, request.knowledge_scope)
                if request.enable_web_search and self.settings.enable_web_search:
                    KnowledgeQuizService.validate_public_topic(request.public_search_topic)
            active = await self.db.scalar(select(QuizGenerationTask.id).where(QuizGenerationTask.user_id == user.id, QuizGenerationTask.status.in_(ACTIVE_STATUSES)).limit(1).with_for_update())
            if active:
                raise ConflictError("你已有生成任务正在处理，请等待任务完成")
            task = QuizGenerationTask(public_id=public_id("qtask"), user_id=user.id, request_id=request.request_id, request_json=payload)
            self.db.add(task)
            created = True
        await self.db.commit()
        if created:
            record_task_created(bool(request.knowledge_scope))
        return await self.view(user, task.public_id)

    async def view(self, user: User, task_id: str) -> dict:
        task = await self.db.scalar(select(QuizGenerationTask).where(QuizGenerationTask.public_id == task_id, QuizGenerationTask.user_id == user.id))
        if not task:
            raise ResourceNotFoundError()
        result = None
        if task.status == "succeeded":
            quiz = await self.db.get(Quiz, task.quiz_id)
            attempt = await self.db.get(LearningAttempt, task.attempt_id)
            if not quiz or not attempt or quiz.user_id != user.id or attempt.user_id != user.id:
                raise ResourceNotFoundError()
            questions = (await self.db.scalars(select(Question).where(Question.quiz_id == quiz.id).order_by(Question.sequence_no))).all()
            result = {"quiz_id": quiz.public_id, "attempt_id": attempt.public_id, "title": quiz.title, "summary": quiz.summary, "user_input": quiz.user_input, "questions": [question_view(q) for q in questions], "source_type": quiz.source_type, "is_private": bool(quiz.knowledge_metadata_json), "web_search": search_view(quiz.web_search_metadata_json)}
        return {"task_id": task.public_id, "status": task.status, "poll_after_ms": TASK_POLL_AFTER_MS, "created_at": task.created_at, "started_at": task.started_at, "completed_at": task.completed_at, "error": {"code": task.error_code, "message": task.error_message} if task.status == "failed" else None, "result": result}


@dataclass(frozen=True)
class TaskClaim:
    task_id: int
    public_id: str
    user_id: int
    token: str
    request_id: str
    payload: dict


class QuizTaskWorker:
    def __init__(self, sessions: async_sessionmaker, settings: Settings, generator: Callable[[], QuizGenerator], search: Callable[[], WebSearchService], *, knowledge_generator=None):
        self.sessions, self.settings = sessions, settings
        self.generator, self.search = generator, search
        self.knowledge_generator = knowledge_generator
        self.runners: list[asyncio.Task] = []

    def start(self) -> None:
        if not self.runners:
            self.runners = [asyncio.create_task(self._loop(), name=f"quiz-worker-{i}") for i in range(self.settings.quiz_task_workers)]

    async def close(self) -> None:
        for runner in self.runners:
            runner.cancel()
        for runner in self.runners:
            with suppress(asyncio.CancelledError):
                await runner
        self.runners.clear()

    async def _loop(self) -> None:
        while True:
            try:
                if await self.run_once():
                    continue
            except Exception as exc:
                # No exception text: provider and database errors can contain secrets.
                log_failure("quiz_worker_error", exc)
            await asyncio.sleep(self.settings.quiz_task_poll_seconds)

    async def expire_stale(self) -> None:
        now = utc_now()
        async with self.sessions() as db:
            async with db.begin():
                await db.execute(update(QuizGenerationTask).where(QuizGenerationTask.status == "running", QuizGenerationTask.lease_expires_at <= now).values(status="failed", error_code="worker_interrupted", error_message="任务执行已中断，请重新生成", completed_at=now, claim_token=None, lease_expires_at=None))
                await db.execute(update(QuizGenerationTask).where(QuizGenerationTask.status == "queued", QuizGenerationTask.created_at <= now-timedelta(seconds=self.settings.quiz_task_queue_timeout_seconds)).values(status="failed", error_code="queue_timeout", error_message="任务排队超时，请稍后重试", completed_at=now))

    async def claim(self) -> TaskClaim | None:
        async with self.sessions() as db:
            async with db.begin():
                task = await db.scalar(select(QuizGenerationTask).where(QuizGenerationTask.status == "queued").order_by(QuizGenerationTask.created_at, QuizGenerationTask.id).limit(1).with_for_update(skip_locked=True))
                if not task:
                    return None
                task.status, task.claim_token, task.started_at = "running", public_id("claim"), utc_now()
                timeout = self.settings.knowledge_quiz_timeout_seconds if task.request_json.get("knowledge_scope") else self.settings.quiz_task_timeout_seconds
                task.lease_expires_at = task.started_at + timedelta(seconds=timeout+15)
                record_task_queue_wait(max(0, (utc_now() - task.created_at).total_seconds()), bool(task.request_json.get("knowledge_scope")))
                return TaskClaim(task.id, task.public_id, task.user_id, task.claim_token, task.request_id, task.request_json)

    async def run_once(self) -> bool:
        await self.expire_stale()
        claim = await self.claim()
        if claim is None:
            return False
        await self.execute(claim)
        return True

    async def execute(self, claim: TaskClaim) -> None:
        started = monotonic()
        outcome = {"status": "internal_error"}
        request_token = request_id_context.set(claim.request_id or "-")
        with task_context(claim.public_id):
            try:
                await self._execute(claim, outcome)
            finally:
                record_task_finished(outcome["status"], bool(claim.payload.get("knowledge_scope")), monotonic() - started)
                request_id_context.reset(request_token)

    async def _execute(self, claim: TaskClaim, outcome: dict[str, str]) -> None:
        is_private = bool(claim.payload.get("knowledge_scope"))
        private_generator = None
        trace = None
        try:
            async with asyncio.timeout(self.settings.knowledge_quiz_timeout_seconds if is_private else self.settings.quiz_task_timeout_seconds):
                snapshots, scopes = None, None
                if is_private:
                    from app.services.knowledge_service import KnowledgeService
                    from app.services.knowledge_quiz_service import KnowledgeQuizService
                    request = QuizTaskCreateRequest.model_validate({**claim.payload, "request_id": claim.public_id})
                    async with self.sessions() as db:
                        user = await db.get(User, claim.user_id)
                        if not user or user.status != "active":
                            raise ResourceNotFoundError()
                        scopes = await KnowledgeService(db, self.settings).resolve_scope(user, request.knowledge_scope)
                    async def validate_scope():
                        async with self.sessions() as check_db:
                            check_user = await check_db.get(User, claim.user_id)
                            if not check_user or check_user.status != "active":
                                raise ResourceNotFoundError()
                            if await KnowledgeService(check_db, self.settings).resolve_scope(check_user, request.knowledge_scope) != scopes:
                                raise KnowledgeError("source_changed", "资料或索引版本已经变化，请重新生成", 409)
                    private_generator = self.knowledge_generator() if self.knowledge_generator else KnowledgeQuizService(
                        self.settings, search=self.search(), scope_validator=validate_scope)
                    result = await private_generator.generate(request, scopes, claim.public_id)
                    trace = getattr(private_generator, "trace", None)
                    generated, snapshots = result.quiz, result.snapshots
                else:
                    request = QuizGenerateRequest.model_validate(claim.payload)
                    generated = await QuizService(self.generator(), ContentFilter(self.settings.blocked_term_list), self.search(), self.settings).generate(request)
                async with self.sessions() as db:
                    async with db.begin():
                        if is_private:
                            # Match submission lock order: user, sources, then task.
                            user = await db.scalar(select(User).where(User.id == claim.user_id).with_for_update())
                            if not user or user.status != "active":
                                raise ResourceNotFoundError()
                            for selection in request.knowledge_scope.documents:
                                await KnowledgeService(db, self.settings).document(user.id, selection.document_id, lock=True)
                            current_scopes = await KnowledgeService(db, self.settings).resolve_scope(user, request.knowledge_scope)
                            if current_scopes != scopes:
                                raise KnowledgeError("source_changed", "资料或索引版本已经变化，请重新生成", 409)
                        task = await db.scalar(select(QuizGenerationTask).where(QuizGenerationTask.id == claim.task_id, QuizGenerationTask.status == "running", QuizGenerationTask.claim_token == claim.token, QuizGenerationTask.lease_expires_at > utc_now()).with_for_update())
                        if not task:
                            outcome["status"] = "stale"
                            return  # A stale worker cannot publish its late result.
                        user = await db.get(User, claim.user_id)
                        if not user or user.status != "active":
                            raise ResourceNotFoundError()
                        quiz = await save_generated_quiz(db, user.id, request, generated, self.settings)
                        if is_private:
                            quiz.source_type, quiz.prompt_version = "knowledge", "knowledge_quiz_v1"
                            quiz.knowledge_metadata_json = {"kind": "knowledge", "scope": request.knowledge_scope.model_dump(mode="json")}
                            questions = (await db.scalars(select(Question).where(Question.quiz_id == quiz.id).order_by(Question.sequence_no))).all()
                            if len(snapshots) != len(questions):
                                raise KnowledgeError("invalid_evidence", "题目引用不完整，请重新生成", 503)
                            for question, snapshot in zip(questions, snapshots):
                                question.source_metadata_json = snapshot
                            await persist_trace(db, trace, task_public_id=claim.public_id, user_id=claim.user_id, status="succeeded")
                        attempt_view = await LearningService(db).create_attempt(user, quiz.public_id, commit=False)
                        attempt = await db.scalar(select(LearningAttempt).where(LearningAttempt.public_id == attempt_view["attempt_id"]))
                        task.status, task.quiz_id, task.attempt_id = "succeeded", quiz.id, attempt.id
                        task.completed_at, task.claim_token, task.lease_expires_at = utc_now(), None, None
                        outcome["status"] = "succeeded"
        except asyncio.CancelledError:
            outcome["status"] = "worker_interrupted"
            await self.fail(claim, "worker_interrupted", "任务执行已中断，请重新生成")
            if is_private:
                await self.save_trace(claim, getattr(private_generator, "trace", trace), "failed", "worker_interrupted", "任务执行已中断")
            raise
        except TimeoutError:
            outcome["status"] = "task_timeout"
            await self.fail(claim, "task_timeout", "知识库出题超时，请缩小资料范围后重试" if is_private else "题目生成超时，请稍后重试")
            if is_private:
                await self.save_trace(claim, getattr(private_generator, "trace", trace), "failed", "task_timeout", "知识库出题超时")
        except Exception as exc:
            outcome["status"] = "failed"
            log_failure("quiz_task_failed", exc, claim.public_id)
            code = exc.reason if isinstance(exc, KnowledgeError) else "generation_failed" if isinstance(exc, AppError) else "internal_error"
            message = exc.public_message if isinstance(exc, KnowledgeError) else "题目生成失败，请稍后重试"
            if is_private and isinstance(exc, (ResourceNotFoundError, ConflictError)):
                code, message = "source_changed", "所选资料已删除或版本已变化，请重新选择"
            await self.fail(claim, code, message)
            if is_private:
                await self.save_trace(claim, getattr(private_generator, "trace", trace), "failed", code, message)

    async def save_trace(self, claim, trace, status, code=None, message=None):
        if not trace:
            return
        async with self.sessions() as db, db.begin():
            await persist_trace(db, trace, task_public_id=claim.public_id, user_id=claim.user_id,
                                status=status, error_code=code, error_message=message)

    async def fail(self, claim: TaskClaim, code: str, message: str) -> None:
        async with self.sessions() as db:
            async with db.begin():
                await db.execute(update(QuizGenerationTask).where(QuizGenerationTask.id == claim.task_id, QuizGenerationTask.status == "running", QuizGenerationTask.claim_token == claim.token).values(status="failed", error_code=code, error_message=message, completed_at=utc_now(), claim_token=None, lease_expires_at=None))
