import pytest
from sqlalchemy import select
from app.core.exceptions import ConflictError
from app.core.knowledge_errors import KnowledgeError
from app.db.models import User, KnowledgeDocumentVersion, KnowledgeProcessingTask
from app.models.knowledge import ChaptersPatch, KnowledgeRequest, TextDocumentInput
from app.services.knowledge_service import KnowledgeService
from app.services.knowledge_task_service import KnowledgeTaskWorker
from app.services.knowledge_processing_service import KnowledgeProcessor
from tests.test_knowledge_processing import processing_env


async def test_commit_failure_cleans_uncommitted_file_without_expired_user_access(processing_env, monkeypatch):
    env = processing_env
    async with env[1]() as db:
        user = await db.get(User, env[3].id)
        service = KnowledgeService(db, env[2])
        base_id = env[5]['document']['knowledge_base_id']
        async def broken(): raise RuntimeError('synthetic commit failure')
        monkeypatch.setattr(db, 'commit', broken)
        with pytest.raises(RuntimeError, match='synthetic commit failure'):
            await service.save_text(user, base_id, TextDocumentInput(title='不能提交的原文', text='合成资料', request_id='failed-commit-00001'))
    assert len(list(env[2].private_directory(env[2].knowledge_storage_directory).rglob('*.txt'))) == 1


async def test_ambiguous_chapter_commit_keeps_committed_parsed_file(processing_env, monkeypatch):
    env = processing_env
    await KnowledgeTaskWorker(env[1], env[2]).run_once()
    async with env[1]() as db:
        service = KnowledgeService(db, env[2]); user = await db.get(User, env[3].id)
        doc_id = env[5]['document']['document_id']; preview = await service.preview(user, doc_id)
        commit = db.commit
        async def ambiguous(): await commit(); raise RuntimeError('synthetic lost acknowledgment')
        monkeypatch.setattr(db, 'commit', ambiguous)
        with pytest.raises(RuntimeError):
            await service.patch_chapters(user, doc_id, ChaptersPatch(version_id=preview['document']['version_id'],
                chapters=[{'title':'全文修正','start_offset':0,'end_offset':preview['total_characters']}]))
    async with env[1]() as db:
        version = await db.scalar(select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.version_no == 2))
        assert version and KnowledgeService(db, env[2]).storage.path(version.parsed_key).exists()


async def test_cleanup_failure_is_visible_and_owned_retry_completes(processing_env):
    env = processing_env
    await KnowledgeTaskWorker(env[1], env[2]).run_once()
    class FailingVectors:
        async def remove_document(self, *args): raise RuntimeError('synthetic disk failure')
    async with env[1]() as db:
        await KnowledgeService(db, env[2]).delete_base(env[3], env[5]['document']['knowledge_base_id'])
    runner = KnowledgeTaskWorker(env[1], env[2], processor=KnowledgeProcessor(env[1], env[2], vector_store=FailingVectors()))
    await runner.run_once()
    async with env[1]() as db:
        task = await db.scalar(select(KnowledgeProcessingTask).where(KnowledgeProcessingTask.task_type == 'cleanup'))
        service = KnowledgeService(db, env[2]); view = await service.task_view(env[3], task.public_id)
        assert view['status'] == 'failed' and view['document']['cleanup_status'] == 'failed'
        listing = await service.list_cleanup_tasks(env[3])
        assert listing['total'] == 1 and listing['items'][0]['task_id'] == task.public_id
        request = KnowledgeRequest(request_id='cleanup-retry-00001')
        retry = await service.retry_task(env[3], task.public_id, request)
        assert (await service.list_cleanup_tasks(env[3]))['items'][0]['task_id'] == retry['task_id']
        assert (await service.retry_task(env[3], task.public_id, request))['task_id'] == retry['task_id']
        with pytest.raises(Exception) as caught: await service.retry_task(env[4], task.public_id, request)
        assert caught.value.status_code == 404
    await KnowledgeTaskWorker(env[1], env[2]).run_once()
    async with env[1]() as db:
        assert (await KnowledgeService(db, env[2]).task_view(env[3], retry['task_id']))['document']['cleanup_status'] == 'complete'
        assert (await KnowledgeService(db, env[2]).list_cleanup_tasks(env[3]))['total'] == 0


async def test_parse_failure_retry_excludes_original_import_tasks(processing_env):
    env = processing_env
    async with env[1]() as db:
        service = KnowledgeService(db, env[2]); await service.cancel_task(env[3], env[5]['task_id'])
        retry = await service.retry_document(env[3], env[5]['document']['document_id'], KnowledgeRequest(request_id='parse-retry-000001'))
        assert retry['task_type'] == 'parse_index'
        with pytest.raises(ConflictError):
            await service.retry_document(env[3], env[5]['document']['document_id'], KnowledgeRequest(request_id='parse-retry-000002'))
