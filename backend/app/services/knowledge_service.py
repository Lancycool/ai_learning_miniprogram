"""Database ownership checks precede every private file or resource read."""

import asyncio
from hashlib import sha256

from sqlalchemy import func, select, update

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.knowledge_errors import KnowledgeError, feature_unavailable
from app.db.base import utc_now
from app.db.models import (KnowledgeBase, KnowledgeDocument, KnowledgeDocumentVersion,
                           KnowledgeChapter, KnowledgeProcessingTask, User)
from app.services.auth_service import public_id
from app.services.knowledge_storage import KnowledgeStorage


class KnowledgeService:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings
        self.storage = KnowledgeStorage(settings)

    def ensure_enabled(self):
        if not self.settings.enable_knowledge_base:
            raise feature_unavailable()

    async def base(self, user_id, base_id, *, lock=False):
        self.ensure_enabled()
        query = select(KnowledgeBase).where(KnowledgeBase.user_id == user_id,
                 KnowledgeBase.public_id == base_id, KnowledgeBase.deleted_at.is_(None))
        resource = await self.db.scalar(query.with_for_update().execution_options(populate_existing=True) if lock else query)
        if not resource:
            raise ResourceNotFoundError()
        return resource

    async def document(self, user_id, document_id, *, lock=False):
        self.ensure_enabled()
        query = select(KnowledgeDocument).join(KnowledgeBase).where(
            KnowledgeDocument.public_id == document_id, KnowledgeDocument.user_id == user_id,
            KnowledgeBase.user_id == user_id, KnowledgeDocument.deleted_at.is_(None), KnowledgeBase.deleted_at.is_(None))
        resource = await self.db.scalar(query.with_for_update().execution_options(populate_existing=True) if lock else query)
        if not resource:
            raise ResourceNotFoundError()
        return resource

    async def version(self, user_id, document, version_id=None):
        query = select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.user_id == user_id,
                 KnowledgeDocumentVersion.document_id == document.id,
                 KnowledgeDocumentVersion.id == document.current_version_id)
        if version_id:
            query = query.where(KnowledgeDocumentVersion.public_id == version_id)
        version = await self.db.scalar(query)
        if not version:
            raise ConflictError("资料版本已经变化，请重新选择")
        return version

    async def base_view(self, base):
        count = await self.db.scalar(select(func.count()).select_from(KnowledgeDocument).where(
            KnowledgeDocument.knowledge_base_id == base.id, KnowledgeDocument.user_id == base.user_id,
            KnowledgeDocument.deleted_at.is_(None)))
        return {"knowledge_base_id": base.public_id, "name": base.name, "description": base.description,
                "cover": base.cover, "document_count": count, "created_at": base.created_at, "updated_at": base.updated_at}

    async def list_bases(self, user, page=1, page_size=20):
        self.ensure_enabled()
        condition = (KnowledgeBase.user_id == user.id, KnowledgeBase.deleted_at.is_(None))
        total = await self.db.scalar(select(func.count()).select_from(KnowledgeBase).where(*condition))
        items = (await self.db.scalars(select(KnowledgeBase).where(*condition).order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
        return {"items": [await self.base_view(x) for x in items], "total": total, "page": page}

    async def create_base(self, user, request):
        self.ensure_enabled()
        await self.db.scalar(select(User.id).where(User.id == user.id).with_for_update())
        count = await self.db.scalar(select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.user_id == user.id, KnowledgeBase.deleted_at.is_(None)))
        if count >= self.settings.knowledge_max_bases:
            raise KnowledgeError("base_limit", "你的知识库数量已达到上限")
        resource = KnowledgeBase(public_id=public_id("kb"), user_id=user.id, **request.model_dump())
        self.db.add(resource)
        await self.db.commit()
        return await self.base_view(resource)

    async def patch_base(self, user, base_id, request):
        resource = await self.base(user.id, base_id, lock=True)
        for key, value in request.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(resource, key, value)
        await self.db.commit()
        return await self.base_view(resource)

    async def document_view(self, doc):
        base_id = await self.db.scalar(select(KnowledgeBase.public_id).where(
            KnowledgeBase.id == doc.knowledge_base_id, KnowledgeBase.user_id == doc.user_id))
        version = await self.db.scalar(select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.id == doc.current_version_id, KnowledgeDocumentVersion.user_id == doc.user_id))
        task = await self.db.scalar(select(KnowledgeProcessingTask).where(KnowledgeProcessingTask.document_id == doc.id,
             KnowledgeProcessingTask.user_id == doc.user_id).order_by(KnowledgeProcessingTask.id.desc()).limit(1))
        return {"document_id": doc.public_id, "knowledge_base_id": base_id, "title": doc.title, "file_type": doc.file_type, "file_size": doc.file_size,
                "version_id": version.public_id if version else None, "version_no": version.version_no if version else None,
                "parse_status": doc.parse_status, "index_status": doc.index_status,
                "cleanup_status": doc.cleanup_status, "deleted": doc.deleted_at is not None,
                "task_id": task.public_id if task else None, "created_at": doc.created_at, "updated_at": doc.updated_at}

    async def list_documents(self, user, base_id, page=1, page_size=20):
        base = await self.base(user.id, base_id)
        condition = (KnowledgeDocument.user_id == user.id, KnowledgeDocument.knowledge_base_id == base.id,
                     KnowledgeDocument.deleted_at.is_(None))
        total = await self.db.scalar(select(func.count()).select_from(KnowledgeDocument).where(*condition))
        docs = (await self.db.scalars(select(KnowledgeDocument).where(*condition).order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
        return {"items": [await self.document_view(d) for d in docs], "total": total, "page": page}

    async def task_view(self, user, task_id):
        self.ensure_enabled()
        task = await self.db.scalar(select(KnowledgeProcessingTask).where(KnowledgeProcessingTask.public_id == task_id,
                                                                          KnowledgeProcessingTask.user_id == user.id))
        if not task:
            raise ResourceNotFoundError()
        doc = await self.db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.id == task.document_id,
                                                                   KnowledgeDocument.user_id == user.id))
        return {"task_id": task.public_id, "status": task.status, "stage": task.stage, "task_type": task.task_type,
                "processed_count": task.processed_count, "total_count": task.total_count, "poll_after_ms": 5000,
                "document": await self.document_view(doc) if doc else None,
                "created_at": task.created_at, "started_at": task.started_at, "completed_at": task.completed_at,
                "error": {"code": task.error_code, "message": task.error_message} if task.status == "failed" else None,
                "result": task.result_json if task.status == "succeeded" else None}

    async def task_by_request(self, user, request_id):
        self.ensure_enabled()
        task_id = await self.db.scalar(select(KnowledgeProcessingTask.public_id).where(
            KnowledgeProcessingTask.user_id == user.id, KnowledgeProcessingTask.request_id == request_id))
        if task_id is None:
            raise ResourceNotFoundError()
        return await self.task_view(user, task_id)

    async def list_cleanup_tasks(self, user, base_id=None, page=1, page_size=20):
        self.ensure_enabled()
        latest = select(func.max(KnowledgeProcessingTask.id)).where(
            KnowledgeProcessingTask.user_id == user.id,
            KnowledgeProcessingTask.task_type == "cleanup").group_by(KnowledgeProcessingTask.document_id)
        query = select(KnowledgeProcessingTask).join(KnowledgeBase).where(
            KnowledgeProcessingTask.user_id == user.id, KnowledgeBase.user_id == user.id,
            KnowledgeProcessingTask.id.in_(latest),
            KnowledgeProcessingTask.status.in_(("queued", "running", "failed")))
        if base_id:
            query = query.where(KnowledgeBase.public_id == base_id)
        total = await self.db.scalar(select(func.count()).select_from(query.subquery()))
        tasks = (await self.db.scalars(query.order_by(KnowledgeProcessingTask.id.desc())
            .offset((page-1)*page_size).limit(page_size))).all()
        return {"items": [await self.task_view(user, task.public_id) for task in tasks], "total": total, "page": page}

    async def upload_document(self, user, base_id, request_id, upload):
        await self.base(user.id, base_id)
        key, title, extension, size, digest = await self.storage.receive(upload, user.public_id)
        try:
            return await self._save_document(user, base_id, request_id, title, extension, size, digest, key)
        finally:
            await self.storage.remove(key)

    async def save_text(self, user, base_id, request):
        await self.base(user.id, base_id)
        if not request.text.strip() or len(request.text) > self.settings.knowledge_max_characters:
            raise KnowledgeError("text_limit", "资料不能为空，且需要在文字处理上限内")
        data = request.text.encode("utf-8")
        if len(data) > self.settings.knowledge_max_file_bytes:
            raise KnowledgeError("file_too_large", "文字资料超过系统允许的大小", 413)
        key = f"{user.public_id}/uploads/{public_id('upload')}.tmp"
        await self.storage.write(key, data)
        try:
            return await self._save_document(user, base_id, request.request_id, request.title, "txt", len(data), sha256(data).hexdigest(), key)
        finally:
            await self.storage.remove(key)

    async def _save_document(self, user, base_id, request_id, title, extension, size, digest, temporary_key):
        user_id = user.id
        await self.db.scalar(select(User.id).where(User.id == user.id).with_for_update())
        base = await self.base(user.id, base_id, lock=True)
        payload = {"action": "upload", "knowledge_base_id": base_id, "title": title, "file_type": extension,
                   "file_size": size, "file_hash": digest}
        previous = await self.db.scalar(select(KnowledgeProcessingTask).where(KnowledgeProcessingTask.user_id == user.id,
                         KnowledgeProcessingTask.request_id == request_id).with_for_update())
        if previous:
            if previous.request_json != payload:
                raise ConflictError("同一请求编号不能用于不同资料")
            await self.db.commit()
            return await self.task_view(user, previous.public_id)
        count, used = (await self.db.execute(select(func.count(), func.coalesce(func.sum(KnowledgeDocument.file_size), 0)).where(
            KnowledgeDocument.user_id == user.id, KnowledgeDocument.deleted_at.is_(None)))).one()
        if count >= self.settings.knowledge_max_documents or used + size > self.settings.knowledge_max_storage_bytes:
            raise KnowledgeError("storage_limit", "你的资料数量或存储量已达到上限，请先清理资料")
        document_id, version_id = public_id("doc"), public_id("ver")
        key = f"{user.public_id}/{document_id}/{version_id}.{extension}"
        path = self.storage.path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(self.storage.path(temporary_key).replace, path)
        try:
            document = KnowledgeDocument(public_id=document_id, user_id=user.id, knowledge_base_id=base.id,
                                         title=title, file_type=extension, file_size=size, file_hash=digest)
            self.db.add(document)
            await self.db.flush()
            version = KnowledgeDocumentVersion(public_id=version_id, user_id=user.id, document_id=document.id,
                                                version_no=1, source_key=key)
            self.db.add(version)
            await self.db.flush()
            document.current_version_id = version.id
            task = self.new_task(user.id, base.id, document.id, version.id, request_id, "parse_index", payload)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            # A commit failure may be ambiguous. Preserve a file if its document was committed.
            saved = await self.db.scalar(select(KnowledgeDocument.id).where(KnowledgeDocument.public_id == document_id,
                                                                           KnowledgeDocument.user_id == user_id))
            if saved is None:
                await self.storage.remove(key)
            raise
        return await self.task_view(user, task.public_id)

    def new_task(self, user_id, base_id, document_id, version_id, request_id, task_type, payload):
        task = KnowledgeProcessingTask(public_id=public_id("ktask"), user_id=user_id, knowledge_base_id=base_id,
                document_id=document_id, version_id=version_id, request_id=request_id, task_type=task_type, request_json=payload)
        self.db.add(task)
        return task

    async def chapters(self, user_id, version):
        return (await self.db.scalars(select(KnowledgeChapter).where(KnowledgeChapter.user_id == user_id,
                   KnowledgeChapter.version_id == version.id).order_by(KnowledgeChapter.sequence_no))).all()

    async def resolve_scope(self, user, request, *, require_index=True):
        from app.services.original_question_parser import merged_ranges
        from app.core.knowledge_runtime import knowledge_capabilities
        base = await self.base(user.id, request.knowledge_base_id)
        fingerprint = None
        if require_index:
            if not knowledge_capabilities(self.settings)["index_available"]:
                raise KnowledgeError("embedding_unavailable", "向量服务配置不可用，请先配置百炼或练习已确认原题", 503)
            from app.services.bailian_embeddings import BailianEmbeddings
            fingerprint = BailianEmbeddings(self.settings).fingerprint
        scopes = []
        for selection in request.documents:
            doc = await self.document(user.id, selection.document_id)
            if doc.knowledge_base_id != base.id:
                raise ResourceNotFoundError()
            version = await self.version(user.id, doc, selection.version_id)
            if not version.parsed_key or doc.parse_status != "ready":
                raise ConflictError("所选资料文字尚未解析完成")
            if require_index and (doc.index_status != "ready" or not version.index_generation
                                  or version.embedding_fingerprint != fingerprint):
                raise ConflictError("所选资料索引未完成或配置已经变化，请先重建索引")
            chapters = await self.chapters(user.id, version)
            values = [chapter_view(c) for c in chapters]
            selected = None if selection.chapter_ids is None else sorted(set(selection.chapter_ids))
            if selected is not None and not set(selected).issubset({c.public_id for c in chapters}):
                raise ConflictError("所选章节已变化，请重新选择")
            ranges = merged_ranges(values, selected)
            allowed = None if selected is None else sorted(c.public_id for c in chapters
                if any(a <= c.start_offset < c.end_offset <= b for a, b in ranges))
            scopes.append({"user_id": user.id, "knowledge_base_id": base.public_id,
                "document_id": doc.public_id, "version_id": version.public_id, "generation": version.index_generation,
                "chapter_ids": allowed, "ranges": ranges, "title": doc.title, "chapters": values,
                "embedding_fingerprint": version.embedding_fingerprint})
        return scopes

    async def cancel_task(self, user, task_id):
        self.ensure_enabled()
        task = await self.db.scalar(select(KnowledgeProcessingTask).where(
            KnowledgeProcessingTask.public_id == task_id, KnowledgeProcessingTask.user_id == user.id).with_for_update())
        if task is None:
            raise ResourceNotFoundError()
        if task.status in ("queued", "running"):
            task.status, task.error_code, task.error_message = "failed", "cancelled", "你已取消资料处理"
            task.completed_at, task.claim_token, task.lease_expires_at = utc_now(), None, None
        await self.db.commit()
        return await self.task_view(user, task_id)

    async def retry_document(self, user, document_id, request):
        await self.db.scalar(select(User.id).where(User.id == user.id).with_for_update())
        doc = await self.document(user.id, document_id, lock=True)
        payload = {"action": "rebuild_index", "document_id": document_id, "version_id": doc.current_version_id}
        previous = await self.db.scalar(select(KnowledgeProcessingTask).where(
            KnowledgeProcessingTask.user_id == user.id, KnowledgeProcessingTask.request_id == request.request_id))
        if previous and previous.request_json == payload:
            await self.db.commit()
            return await self.task_view(user, previous.public_id)
        if doc.parse_status == "ready":
            if previous:
                raise ConflictError("同一请求编号不能用于不同处理任务")
            active = await self.db.scalar(select(KnowledgeProcessingTask.id).where(
                KnowledgeProcessingTask.document_id == doc.id, KnowledgeProcessingTask.user_id == user.id,
                KnowledgeProcessingTask.status.in_(("queued", "running"))))
            if active:
                raise ConflictError("请等待当前资料任务结束后重建索引")
            task = self.new_task(user.id, doc.knowledge_base_id, doc.id, doc.current_version_id,
                request.request_id, "index", payload)
            doc.index_status = "queued"
            await self.db.commit()
            return await self.task_view(user, task.public_id)
        task_id = await self.db.scalar(select(KnowledgeProcessingTask.public_id).where(
            KnowledgeProcessingTask.document_id == doc.id, KnowledgeProcessingTask.user_id == user.id,
            KnowledgeProcessingTask.version_id == doc.current_version_id,
            KnowledgeProcessingTask.task_type.in_(("parse_index", "index")),
            KnowledgeProcessingTask.status == "failed").order_by(KnowledgeProcessingTask.id.desc()).limit(1))
        if not task_id:
            raise ConflictError("资料没有需要重试的失败任务")
        return await self.retry_task(user, task_id, request)

    async def retry_task(self, user, task_id, request):
        self.ensure_enabled()
        await self.db.scalar(select(User.id).where(User.id == user.id).with_for_update())
        old = await self.db.scalar(select(KnowledgeProcessingTask).where(
            KnowledgeProcessingTask.public_id == task_id, KnowledgeProcessingTask.user_id == user.id))
        if old is None:
            raise ResourceNotFoundError()
        doc = await self.db.scalar(select(KnowledgeDocument).where(
            KnowledgeDocument.id == old.document_id, KnowledgeDocument.user_id == user.id).with_for_update())
        if old.task_type != "cleanup":
            await self.document(user.id, doc.public_id)
            if doc.current_version_id != old.version_id:
                raise ConflictError("资料版本已变化，请选择当前版本")
        payload = {**old.request_json, "retry_of": old.public_id}
        previous = await self.db.scalar(select(KnowledgeProcessingTask).where(
            KnowledgeProcessingTask.user_id == user.id, KnowledgeProcessingTask.request_id == request.request_id))
        if previous:
            if previous.request_json != payload:
                raise ConflictError("同一请求编号不能重试不同任务")
            await self.db.commit()
            return await self.task_view(user, previous.public_id)
        active = await self.db.scalar(select(KnowledgeProcessingTask.id).where(
            KnowledgeProcessingTask.document_id == doc.id, KnowledgeProcessingTask.user_id == user.id,
            KnowledgeProcessingTask.status.in_(("queued", "running"))))
        if old.status != "failed" or active:
            raise ConflictError("请等待当前任务结束后重试")
        task = self.new_task(user.id, doc.knowledge_base_id, doc.id, old.version_id,
            request.request_id, old.task_type, payload)
        if old.task_type == "cleanup":
            doc.cleanup_status = "pending"
        elif old.task_type in ("parse_index", "index"):
            if doc.parse_status != "ready":
                doc.parse_status = "queued"
            doc.index_status = "queued"
        await self.db.commit()
        return await self.task_view(user, task.public_id)

    async def preview(self, user, document_id, offset=0, limit=4000):
        doc = await self.document(user.id, document_id)
        version = await self.version(user.id, doc)
        if not version.parsed_key or doc.parse_status != "ready":
            raise ConflictError("资料文字尚未解析完成，请稍后查看")
        parsed = await self.storage.read_parsed(version.parsed_key)
        chapters = await self.chapters(user.id, version)
        text = parsed["text"]
        return {"document": await self.document_view(doc), "text": text[offset:offset+limit], "offset": offset,
                "total_characters": len(text), "has_more": offset + limit < len(text), "warnings": version.parse_warnings_json,
                "chapters": [chapter_view(c) for c in chapters]}

    async def patch_chapters(self, user, document_id, request):
        user_id = user.id
        from app.services.knowledge_processing_service import add_chapters
        doc = await self.document(user.id, document_id, lock=True)
        old = await self.version(user.id, doc, request.version_id)
        if not old.parsed_key or doc.parse_status != "ready":
            raise ConflictError("资料文字尚未解析完成")
        parsed = await self.storage.read_parsed(old.parsed_key)
        chapters = sorted([c.model_dump() for c in request.chapters], key=lambda c: (c["start_offset"], c["level"]))
        boundaries = sorted({0, len(parsed["text"])} | {c[k] for c in chapters for k in ("start_offset", "end_offset")})
        if any(c["end_offset"] > len(parsed["text"]) for c in chapters):
            raise KnowledgeError("invalid_chapters", "章节范围超出原文")
        for start, end in zip(boundaries, boundaries[1:]):
            active = [c for c in chapters if c["start_offset"] <= start and c["end_offset"] >= end]
            if not active or len({c["level"] for c in active}) != len(active):
                raise KnowledgeError("invalid_chapters", "章节需要覆盖全文，同一层级的范围不能重叠")
        for a in chapters:
            for b in chapters:
                if a["level"] < b["level"] and a["start_offset"] < b["end_offset"] and b["start_offset"] < a["end_offset"]:
                    if not a["start_offset"] <= b["start_offset"] < b["end_offset"] <= a["end_offset"]:
                        raise KnowledgeError("invalid_chapters", "子章节需要完整位于父章节范围内")
        version_id = public_id("ver")
        key = f"parsed/{user.id}/{document_id}/{version_id}.json"
        await self.storage.write_parsed(key, {**parsed, "chapters": chapters})
        try:
            version = KnowledgeDocumentVersion(public_id=version_id, user_id=user.id, document_id=doc.id,
                version_no=old.version_no+1, source_key=old.source_key, parsed_key=key,
                text_length=old.text_length, parse_warnings_json=old.parse_warnings_json)
            self.db.add(version)
            await self.db.flush()
            add_chapters(self.db, user.id, version.id, chapters)
            await self.db.execute(update(KnowledgeProcessingTask).where(
                KnowledgeProcessingTask.document_id == doc.id, KnowledgeProcessingTask.user_id == user.id,
                KnowledgeProcessingTask.status.in_(("queued", "running"))).values(status="failed",
                error_code="source_changed", error_message="章节版本已更新，请重新选择", completed_at=utc_now(),
                claim_token=None, lease_expires_at=None))
            doc.current_version_id, doc.index_status = version.id, "queued"
            task = self.new_task(user.id, doc.knowledge_base_id, doc.id, version.id, public_id("chapters"),
                "index", {"version_id": version_id, "action": "chapters"})
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            saved = await self.db.scalar(select(KnowledgeDocumentVersion.id).where(
                KnowledgeDocumentVersion.public_id == version_id, KnowledgeDocumentVersion.user_id == user_id))
            if saved is None:
                await self.storage.remove(key)
            raise
        return await self.task_view(user, task.public_id)

    async def delete_document(self, user, document_id, *, commit=True):
        doc = await self.document(user.id, document_id, lock=True)
        doc.deleted_at, doc.cleanup_status = utc_now(), "pending"
        await self.db.execute(update(KnowledgeProcessingTask).where(KnowledgeProcessingTask.document_id == doc.id,
             KnowledgeProcessingTask.user_id == user.id, KnowledgeProcessingTask.status.in_(("queued", "running"))).values(
             status="failed", error_code="source_deleted", error_message="原资料已删除", completed_at=utc_now(),
             claim_token=None, lease_expires_at=None))
        task = self.new_task(user.id, doc.knowledge_base_id, doc.id, doc.current_version_id,
                      public_id("delete"), "cleanup", {"document_id": doc.public_id})
        if commit:
            await self.db.commit()
        return {"document_id": doc.public_id, "cleanup_status": "pending", "cleanup_task_id": task.public_id,
                "learning_snapshots_retained": True}

    async def delete_base(self, user, base_id):
        base = await self.base(user.id, base_id, lock=True)
        docs = (await self.db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.user_id == user.id,
                    KnowledgeDocument.knowledge_base_id == base.id, KnowledgeDocument.deleted_at.is_(None)))).all()
        cleanup_ids = []
        for document in docs:
            deleted = await self.delete_document(user, document.public_id, commit=False)
            cleanup_ids.append(deleted["cleanup_task_id"])
        base.deleted_at = utc_now()
        await self.db.commit()
        return {"knowledge_base_id": base.public_id, "cleanup_status": "pending" if docs else "complete",
                "cleanup_task_ids": cleanup_ids, "learning_snapshots_retained": True}


def chapter_view(chapter):
    return {"chapter_id": chapter.public_id, "title": chapter.title, "level": chapter.level,
            "parent_chapter_id": chapter.parent_public_id, "sequence_no": chapter.sequence_no,
            "start_offset": chapter.start_offset, "end_offset": chapter.end_offset}
