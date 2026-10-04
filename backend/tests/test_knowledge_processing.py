import asyncio

import pytest
from sqlalchemy import select

from app.core.knowledge_errors import KnowledgeError
from app.db.models import KnowledgeChapter, KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeProcessingTask
from app.models.knowledge import ChaptersPatch, KnowledgeBaseInput, KnowledgeRequest, TextDocumentInput
from app.services.knowledge_service import KnowledgeService
from app.services.knowledge_task_service import KnowledgeTaskWorker
from tests.knowledge_helpers import make_knowledge_env


@pytest.fixture
async def processing_env(tmp_path):
    env = await make_knowledge_env(tmp_path)
    async with env[1]() as db:
        service = KnowledgeService(db, env[2])
        base = await service.create_base(env[3], KnowledgeBaseInput(name="培训"))
        task = await service.save_text(env[3], base["knowledge_base_id"], TextDocumentInput(title="说明",
            text="介绍\n第一章 客服\n客服先核对订单。\n第二章 退款\n退款需要主管确认。", request_id="process-request-0001"))
    yield (*env, task)
    await env[0].dispose()


async def test_real_processing_keeps_preview_when_embedding_not_configured(processing_env):
    env = processing_env
    runner = KnowledgeTaskWorker(env[1], env[2])
    assert await runner.run_once()
    async with env[1]() as db:
        service = KnowledgeService(db, env[2])
        view = await service.task_view(env[3], env[5]["task_id"])
        assert view["status"] == "succeeded" and view["document"]["parse_status"] == "ready"
        assert view["document"]["index_status"] == "unavailable"
        doc_id = env[5]["document"]["document_id"]
        preview = await service.preview(env[3], doc_id, 0, 5)
        assert preview["has_more"] and preview["text"] == "介绍\n第一"
        rest = await service.preview(env[3], doc_id, 5, 4000)
        assert "退款需要主管确认。" in rest["text"]
        assert len(preview["chapters"]) == 3
        with pytest.raises(Exception) as caught:
            await service.preview(env[4], doc_id)
        assert caught.value.status_code == 404


async def test_chapter_revision_creates_version_and_invalidates_old_work(processing_env):
    env = processing_env
    runner = KnowledgeTaskWorker(env[1], env[2])
    await runner.run_once()
    async with env[1]() as db:
        service = KnowledgeService(db, env[2])
        doc_id = env[5]["document"]["document_id"]
        preview = await service.preview(env[3], doc_id)
        original_version = preview["document"]["version_id"]
        request = ChaptersPatch(version_id=original_version, chapters=[{"title": "修正全文", "level": 1,
            "start_offset": 0, "end_offset": preview["total_characters"]}])
        revised = await service.patch_chapters(env[3], doc_id, request)
        assert revised["document"]["version_id"] != original_version
        assert revised["document"]["version_no"] == 2
        assert revised["status"] == "queued"
        with pytest.raises(Exception) as caught:
            await service.patch_chapters(env[3], doc_id, request)
        assert caught.value.status_code == 409
    await runner.run_once()
    async with env[1]() as db:
        preview = await KnowledgeService(db, env[2]).preview(env[3], doc_id)
        assert [c["title"] for c in preview["chapters"]] == ["修正全文"]


async def test_late_index_cannot_publish_after_delete(processing_env):
    from app.services.knowledge_processing_service import KnowledgeProcessor
    env = processing_env
    entered, released = asyncio.Event(), asyncio.Event()
    class Vectors:
        fingerprint = "synthetic"
        discarded = False
        async def write(self, *args, **kwargs):
            entered.set()
            await released.wait()
            return 1
        async def remove_generation(self, scope):
            self.discarded = True
    vectors = Vectors()
    processor = KnowledgeProcessor(env[1], env[2], vector_store=vectors)
    runner = KnowledgeTaskWorker(env[1], env[2], processor=processor)
    running = asyncio.create_task(runner.run_once())
    await asyncio.wait_for(entered.wait(), 30)
    async with env[1]() as db:
        await KnowledgeService(db, env[2]).delete_document(env[3], env[5]["document"]["document_id"])
    released.set()
    await running
    async with env[1]() as db:
        version = await db.scalar(select(KnowledgeDocumentVersion))
        assert version.index_generation is None
    assert vectors.discarded


async def test_index_error_keeps_parsed_original_and_cleanup_deletes_files(processing_env):
    from app.services.knowledge_processing_service import KnowledgeProcessor
    env = processing_env
    class Vectors:
        fingerprint = "synthetic"
        async def write(self, *args, **kwargs):
            raise KnowledgeError("embedding_unavailable", "向量服务暂时不可用", 503)
        async def remove_document(self, *args):
            pass
    runner = KnowledgeTaskWorker(env[1], env[2], processor=KnowledgeProcessor(env[1], env[2], vector_store=Vectors()))
    await runner.run_once()
    async with env[1]() as db:
        service = KnowledgeService(db, env[2])
        view = await service.task_view(env[3], env[5]["task_id"])
        assert view["status"] == "failed" and view["error"]["code"] == "embedding_unavailable"
        preview = await service.preview(env[3], env[5]["document"]["document_id"])
        assert "客服先核对订单。" in preview["text"]
        await service.delete_document(env[3], env[5]["document"]["document_id"])
    await runner.run_once()
    root = env[2].private_directory(env[2].knowledge_storage_directory)
    assert not [p for p in root.rglob("*") if p.is_file()]
    async with env[1]() as db:
        doc = await db.scalar(select(KnowledgeDocument))
        assert doc.cleanup_status == "complete"


async def test_retry_and_cancel_are_owned_idempotent_and_version_bound(processing_env):
    env = processing_env
    async with env[1]() as db:
        service = KnowledgeService(db, env[2])
        cancelled = await service.cancel_task(env[3], env[5]["task_id"])
        assert cancelled["status"] == "failed" and cancelled["error"]["code"] == "cancelled"
        request = KnowledgeRequest(request_id="processing-retry-0001")
        retry = await service.retry_task(env[3], env[5]["task_id"], request)
        same = await service.retry_task(env[3], env[5]["task_id"], request)
        assert retry["task_id"] == same["task_id"] and retry["status"] == "queued"
        with pytest.raises(Exception) as caught:
            await service.cancel_task(env[4], retry["task_id"])
        assert caught.value.status_code == 404
    await KnowledgeTaskWorker(env[1], env[2]).run_once()
    async with env[1]() as db:
        service = KnowledgeService(db, env[2])
        preview = await service.preview(env[3], env[5]["document"]["document_id"])
        assert preview["text"].endswith("退款需要主管确认。")


async def test_invalid_chapter_ranges_never_create_partial_versions(processing_env):
    env = processing_env
    await KnowledgeTaskWorker(env[1], env[2]).run_once()
    async with env[1]() as db:
        service = KnowledgeService(db, env[2])
        preview = await service.preview(env[3], env[5]["document"]["document_id"])
        for ranges in ([{"title": "越界", "start_offset": 0, "end_offset": 9999}],
                       [{"title": "遗漏开头", "start_offset": 4, "end_offset": preview["total_characters"]}]):
            with pytest.raises(KnowledgeError):
                await service.patch_chapters(env[3], env[5]["document"]["document_id"], ChaptersPatch(
                    version_id=preview["document"]["version_id"], chapters=ranges))
        assert len((await db.scalars(select(KnowledgeDocumentVersion))).all()) == 1


async def test_ready_text_can_rebuild_index_and_rebuild_is_idempotent(processing_env):
    env = processing_env
    await KnowledgeTaskWorker(env[1], env[2]).run_once()
    async with env[1]() as db:
        service = KnowledgeService(db, env[2])
        doc_id = env[5]['document']['document_id']
        request = KnowledgeRequest(request_id='rebuild-index-00001')
        task = await service.retry_document(env[3], doc_id, request)
        same = await service.retry_document(env[3], doc_id, request)
        assert task['task_id'] == same['task_id']
        assert task['task_type'] == 'index' and task['document']['parse_status'] == 'ready'
        assert (await service.preview(env[3], doc_id))['text'].endswith('退款需要主管确认。')
        with pytest.raises(Exception) as caught:
            await service.retry_document(env[4], doc_id, request)
        assert caught.value.status_code == 404
