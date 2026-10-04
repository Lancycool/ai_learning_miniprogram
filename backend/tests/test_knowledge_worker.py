import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.db.base import utc_now
from app.db.models import KnowledgeDocument, KnowledgeProcessingTask
from app.models.knowledge import KnowledgeBaseInput, TextDocumentInput
from app.services.knowledge_service import KnowledgeService
from tests.knowledge_helpers import make_knowledge_env


@pytest.fixture
async def worker_env(tmp_path):
    env = await make_knowledge_env(tmp_path)
    async with env[1]() as db:
        service = KnowledgeService(db, env[2])
        base = await service.create_base(env[3], KnowledgeBaseInput(name="员工培训"))
        task = await service.save_text(env[3], base["knowledge_base_id"], TextDocumentInput(
            title="流程", text="第一章\n客服核对订单。", request_id="worker-request-0001"))
    yield (*env, task)
    await env[0].dispose()


def worker(env, processor):
    from app.services.knowledge_task_service import KnowledgeTaskWorker
    return KnowledgeTaskWorker(env[1], env[2], processor=processor)


class Processor:
    async def process(self, claim, progress):
        await progress("parsing", 1, 1)
        return {"parsed": True}

    async def publish(self, db, claim, result):
        assert result == {"parsed": True}
        document = await db.get(KnowledgeDocument, claim.document_id)
        document.parse_status = "ready"
        return {"parsed": True}


async def test_claim_is_exclusive_and_work_releases_database_connections(worker_env):
    runner = worker(worker_env, Processor())
    one, two = await asyncio.gather(runner.claim(), runner.claim())
    assert (one is None) != (two is None)
    assert worker_env[0].pool.checkedout() == 0
    await runner.execute(one or two)
    assert worker_env[0].pool.checkedout() == 0
    async with worker_env[1]() as db:
        task = await db.scalar(select(KnowledgeProcessingTask))
        assert task.status == "succeeded" and task.result_json == {"parsed": True}
        assert task.claim_token is None and task.lease_expires_at is None
        assert task.processed_count == task.total_count == 1


async def test_deleted_source_rejects_late_result(worker_env):
    runner = worker(worker_env, Processor())
    claim = await runner.claim()
    async with worker_env[1]() as db:
        await KnowledgeService(db, worker_env[2]).delete_document(worker_env[3], worker_env[5]["document"]["document_id"])
    await runner.execute(claim)
    async with worker_env[1]() as db:
        task = await db.get(KnowledgeProcessingTask, claim.task_id)
        document = await db.get(KnowledgeDocument, claim.document_id)
        assert task.status == "failed" and task.result_json is None
        assert document.parse_status != "ready"


async def test_provider_failure_is_controlled_and_does_not_log_private_text(worker_env, caplog):
    class Broken(Processor):
        async def process(self, claim, progress):
            raise RuntimeError("PRIVATE_BODY SECRET_API_KEY")
    runner = worker(worker_env, Broken())
    assert await runner.run_once() is True
    async with worker_env[1]() as db:
        task = await db.scalar(select(KnowledgeProcessingTask))
        assert task.status == "failed" and task.error_code == "processing_failed"
        assert "PRIVATE_BODY" not in task.error_message
    assert "PRIVATE_BODY" not in caplog.text and "SECRET_API_KEY" not in caplog.text


async def test_timeout_and_cancel_have_terminal_states(worker_env):
    class Slow(Processor):
        async def process(self, claim, progress):
            await asyncio.Event().wait()
    runner = worker(worker_env, Slow())
    claim = await runner.claim()
    worker_env[2].knowledge_task_timeout_seconds = 0.01
    await runner.execute(claim)
    async with worker_env[1]() as db:
        task = await db.get(KnowledgeProcessingTask, claim.task_id)
        assert task.error_code == "task_timeout"
        task.status = "queued"
        await db.commit()
    claim = await runner.claim()
    worker_env[2].knowledge_task_timeout_seconds = 600
    running = asyncio.create_task(runner.execute(claim))
    await asyncio.sleep(0.05)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    async with worker_env[1]() as db:
        task = await db.get(KnowledgeProcessingTask, claim.task_id)
        assert task.error_code == "worker_interrupted" and task.claim_token is None


async def test_stale_lease_and_queue_are_recovered_without_republishing(worker_env):
    runner = worker(worker_env, Processor())
    claim = await runner.claim()
    async with worker_env[1]() as db:
        await db.execute(update(KnowledgeProcessingTask).values(lease_expires_at=utc_now()-timedelta(seconds=1)))
        await db.commit()
    await runner.expire_stale()
    await runner.execute(claim)
    async with worker_env[1]() as db:
        task = await db.get(KnowledgeProcessingTask, claim.task_id)
        assert task.error_code == "worker_interrupted" and task.result_json is None
        task.status, task.created_at = "queued", utc_now()-timedelta(seconds=601)
        await db.commit()
    await runner.expire_stale()
    assert await runner.claim() is None
    async with worker_env[1]() as db:
        task = await db.get(KnowledgeProcessingTask, claim.task_id)
        assert task.error_code == "queue_timeout"


async def test_start_close_is_idempotent(worker_env):
    runner = worker(worker_env, Processor())
    runner.start()
    first = runner.runner
    runner.start()
    assert runner.runner is first
    await runner.close()
    await runner.close()
    assert runner.runner is None
