"""Parse independently, publish text, then build a complete unpublished index."""

from sqlalchemy import select

from app.core.knowledge_errors import KnowledgeError
from app.core.knowledge_runtime import knowledge_capabilities
from app.db.models import KnowledgeBase, KnowledgeChapter, KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeProcessingTask
from app.services.auth_service import public_id
from app.services.knowledge_parser import KnowledgeParser
from app.services.knowledge_service import chapter_view
from app.services.knowledge_storage import KnowledgeStorage


def add_chapters(db, user_id, version_id, chapters):
    stack = []
    for number, item in enumerate(chapters, 1):
        while stack and stack[-1].level >= item["level"]:
            stack.pop()
        chapter = KnowledgeChapter(public_id=public_id("chapter"), user_id=user_id, version_id=version_id,
            title=item["title"], level=item["level"], sequence_no=number, start_offset=item["start_offset"],
            end_offset=item["end_offset"], parent_public_id=stack[-1].public_id if stack else None)
        db.add(chapter)
        stack.append(chapter)


class KnowledgeProcessor:
    def __init__(self, sessions, settings, *, parser=None, vector_store=None):
        self.sessions, self.settings = sessions, settings
        self.storage, self.parser = KnowledgeStorage(settings), parser or KnowledgeParser(settings)
        self.vectors = vector_store

    def vector_store(self):
        if self.vectors is None:
            from app.services.bailian_embeddings import BailianEmbeddings
            from app.services.knowledge_vector_store import KnowledgeVectorStore
            self.vectors = KnowledgeVectorStore(self.settings, BailianEmbeddings(self.settings))
        return self.vectors

    async def process(self, claim, progress):
        if claim.task_type == "cleanup":
            return await self.cleanup(claim, progress)
        if claim.task_type == "original_import":
            return await self.import_originals(claim, progress)
        if claim.task_type == "original_practice":
            await progress("preparing_practice")
            return claim.payload
        if claim.task_type not in ("parse_index", "index"):
            raise KnowledgeError("unsupported_task", "资料任务类型暂不支持")
        await progress("parsing")
        if claim.parsed_key:
            parsed = await self.storage.read_parsed(claim.parsed_key)
        else:
            parsed = await self.parser.parse(self.storage.path(claim.source_key), claim.file_type)
            await progress("chapters", len(parsed["chapters"]), len(parsed["chapters"]))
            await self.publish_text(claim, parsed)
        async with self.sessions() as db:
            document = await db.get(KnowledgeDocument, claim.document_id)
            base = await db.get(KnowledgeBase, document.knowledge_base_id)
            chapters = (await db.scalars(select(KnowledgeChapter).where(KnowledgeChapter.user_id == claim.user_id,
                KnowledgeChapter.version_id == claim.version_id).order_by(KnowledgeChapter.sequence_no))).all()
            scope = {"user_id": claim.user_id, "knowledge_base_id": base.public_id,
                "document_id": claim.document_public_id, "version_id": claim.version_public_id,
                "title": document.title, "generation": public_id("index")}
            chapter_data = [chapter_view(c) for c in chapters]
        if self.vectors is None and not knowledge_capabilities(self.settings)["index_available"]:
            return {"index_available": False}
        vectors = self.vector_store()
        await progress("indexing", 0)
        count = await vectors.write(scope, parsed["text"], chapter_data, progress=progress)
        return {"index_available": True, "scope": scope, "chunk_count": count,
                "fingerprint": vectors.fingerprint}

    async def publish_text(self, claim, parsed):
        key = f"parsed/{claim.user_id}/{claim.document_public_id}/{claim.version_public_id}.json"
        await self.storage.write_parsed(key, parsed)
        committed = False
        try:
            async with self.sessions() as db, db.begin():
                from app.services.knowledge_task_service import KnowledgeTaskWorker
                task = await KnowledgeTaskWorker(self.sessions, self.settings, processor=self).current(db, claim)
                if task is None:
                    raise KnowledgeError("source_changed", "资料任务已结束", 409)
                version = await db.get(KnowledgeDocumentVersion, claim.version_id)
                if version.parsed_key is not None:
                    raise KnowledgeError("source_changed", "资料文字已更新，请重试", 409)
                version.parsed_key, version.text_length = key, len(parsed["text"])
                version.parse_warnings_json = parsed["warnings"]
                add_chapters(db, claim.user_id, claim.version_id, parsed["chapters"])
                document = await db.get(KnowledgeDocument, claim.document_id)
                document.parse_status = "ready"
            committed = True
        finally:
            if not committed:
                await self.storage.remove(key)

    async def publish(self, db, claim, result):
        doc = await db.get(KnowledgeDocument, claim.document_id)
        if claim.task_type == "original_practice":
            from app.db.models import User
            from app.services.original_question_service import OriginalQuestionService
            return await OriginalQuestionService(db, self.settings).publish_practice(await db.get(User, claim.user_id), result)
        if claim.task_type == "original_import":
            from app.db.models import QuestionImportDraft
            draft = QuestionImportDraft(public_id=public_id("import"), user_id=claim.user_id,
                document_id=claim.document_id, version_id=claim.version_id, title=doc.title[:80],
                chapter_ids_json=claim.payload.get("chapter_ids") or [], items_json=result["items"],
                coverage_json=result["coverage"], issues_json=result["issues"])
            db.add(draft)
            await db.flush()
            return {"draft_id": draft.public_id, "question_count": len(result["items"]), "requires_review": True}
        if claim.task_type == "cleanup":
            doc.cleanup_status = "complete"
            return {"cleanup_status": "complete", "learning_snapshots_retained": True}
        version = await db.get(KnowledgeDocumentVersion, claim.version_id)
        if result["index_available"]:
            version.index_generation = result["scope"]["generation"]
            version.embedding_fingerprint, version.chunk_count = result["fingerprint"], result["chunk_count"]
            doc.index_status = "ready"
        else:
            doc.index_status = "unavailable"
        return {"parsed": True, "index_available": result["index_available"], "chunk_count": version.chunk_count}

    async def discard(self, claim, result):
        if result and result.get("scope"):
            await self.vector_store().remove_generation(result["scope"])

    async def cleanup(self, claim, progress):
        async with self.sessions() as db:
            doc = await db.get(KnowledgeDocument, claim.document_id)
            base = await db.get(KnowledgeBase, doc.knowledge_base_id)
            versions = (await db.scalars(select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.document_id == claim.document_id,
                KnowledgeDocumentVersion.user_id == claim.user_id))).all()
            keys = {v.source_key for v in versions} | {v.parsed_key for v in versions if v.parsed_key}
            base_id = base.public_id
        await progress("cleaning", 0, len(keys))
        if self.vectors is not None:
            await self.vectors.remove_document(claim.user_id, base_id, claim.document_public_id)
        elif self.settings.private_directory(self.settings.chroma_persist_directory).exists():
            from langchain_core.embeddings import Embeddings
            from app.services.knowledge_vector_store import KnowledgeVectorStore
            class CleanupOnly(Embeddings):
                fingerprint = "cleanup-only"
                def embed_documents(self, texts):
                    raise KnowledgeError("cleanup_only", "清理任务不能调用向量服务")
                def embed_query(self, text):
                    raise KnowledgeError("cleanup_only", "清理任务不能调用向量服务")
            await KnowledgeVectorStore(self.settings, CleanupOnly()).remove_document(claim.user_id, base_id, claim.document_public_id)
        for count, key in enumerate(keys, 1):
            await self.storage.remove(key)
            await progress("cleaning", count, len(keys))
        return {"cleanup_status": "complete"}

    async def import_originals(self, claim, progress):
        from app.services.original_question_parser import OriginalQuestionParser
        if not claim.parsed_key:
            raise KnowledgeError("parse_pending", "请等待资料文字解析完成", 409)
        parsed = await self.storage.read_parsed(claim.parsed_key)
        async with self.sessions() as db:
            chapters = (await db.scalars(select(KnowledgeChapter).where(
                KnowledgeChapter.user_id == claim.user_id, KnowledgeChapter.version_id == claim.version_id)
                .order_by(KnowledgeChapter.sequence_no))).all()
            values = [chapter_view(c) for c in chapters]
        await progress("extracting", 0)
        helper = None
        if self.settings.api_key:
            from app.llm.original_locator import OriginalStructureLocator
            helper = OriginalStructureLocator(self.settings)
        result = await OriginalQuestionParser(self.settings, helper=helper).parse(parsed["text"], values,
            selected_ids=claim.payload.get("chapter_ids"), progress=progress)
        result["issues"].extend(parsed.get("warnings", []))
        await progress("review_ready", len(result["items"]), len(result["items"]))
        return result
