import asyncio
import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, inspect, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.db.base import Base, utc_now
from app.db.models import LearningAttempt, Question, Quiz, QuizGenerationTask, User
from app.main import app
from app.models.quiz import QuizDraft
from app.services.learning_service import LearningService
from app.services.quiz_task_service import QuizTaskWorker
from app.services.web_search_service import WebSearchService
from tests.test_services import build_questions
from tests.test_web_search import EnhancedGenerator, Provider, response as search_response, settings as search_settings


class Generator:
    def __init__(self, *, blocked=False, broken=False):
        self.calls = 0
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.broken = broken
        if not blocked:
            self.release.set()

    async def generate(self, request):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        if self.broken:
            raise RuntimeError("provider error with a secret that must not be returned")
        return QuizDraft(title="AI 学习", summary="学习 AI", questions=build_questions())


@pytest.fixture
async def task_env():
    engine = create_async_engine(get_settings().test_database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(_env_file=None, ENABLE_WEB_SEARCH=False, QUIZ_TASK_POLL_SECONDS=0.01, QUIZ_TASK_TIMEOUT_SECONDS=2, QUIZ_GENERATION_BUDGET_SECONDS=1)
    async with sessions() as db:
        user, other = User(public_id="usr-task"), User(public_id="usr-other")
        db.add_all([user, other])
        await db.commit()
    async def db_override():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = db_override
    yield sessions, settings, user, other
    await engine.dispose()


def worker(env, generator):
    sessions, settings, _, _ = env
    return QuizTaskWorker(sessions, settings, lambda: generator, lambda: WebSearchService(settings))


def payload(request_id="request_task_0001", **extra):
    return {"request_id": request_id, "user_input": "AI 基础", **extra}


def client():
    return AsyncClient(transport=ASGITransport(app), base_url="http://test")


async def test_create_returns_before_generation_and_polling_publishes_one_result(task_env):
    generator = Generator(blocked=True)
    runner = worker(task_env, generator)
    async with client() as api:
        created = await api.post("/api/v1/quizzes/generation-tasks", json=payload())
        assert created.status_code == 202
        task = created.json()["data"]
        assert task["poll_after_ms"] == 5000
        assert task["status"] == "queued" and task["result"] is None and generator.calls == 0
        task_id = task["task_id"]
        operation = asyncio.create_task(runner.run_once())
        await asyncio.wait_for(generator.entered.wait(), 1)
        running = (await api.get(f"/api/v1/quizzes/generation-tasks/{task_id}")).json()["data"]
        assert running["status"] == "running" and running["result"] is None
        generator.release.set()
        await operation
        completed = (await api.get(f"/api/v1/quizzes/generation-tasks/{task_id}")).json()["data"]
        assert completed["status"] == "succeeded" and completed["error"] is None
        quiz = completed["result"]
        assert len(quiz["questions"]) == 5
        assert "answer" not in quiz["questions"][0]
        assert quiz["web_search"]["status"] == "disabled" and quiz["web_search"]["sources"] == []
        duplicate = (await api.post("/api/v1/quizzes/generation-tasks", json=payload())).json()["data"]
        assert duplicate["task_id"] == task_id and duplicate["result"]["attempt_id"] == quiz["attempt_id"]
        assert (await api.get(f"/api/v1/attempts/{quiz['attempt_id']}")).status_code == 200
        assert len((await api.get("/api/v1/learning/history")).json()["data"]) == 1
        assert not await runner.run_once() and generator.calls == 1
        app.dependency_overrides[get_current_user] = lambda: task_env[3]
        assert (await api.get(f"/api/v1/quizzes/generation-tasks/{task_id}")).status_code == 404


async def test_concurrent_duplicate_submission_and_active_task_guard(task_env):
    async with client() as api:
        responses = await asyncio.gather(*[api.post("/api/v1/quizzes/generation-tasks", json=payload()) for _ in range(2)])
        assert [r.status_code for r in responses] == [202, 202]
        assert responses[0].json()["data"]["task_id"] == responses[1].json()["data"]["task_id"]
        assert (await api.post("/api/v1/quizzes/generation-tasks", json=payload(user_input="另一主题"))).status_code == 409
        assert (await api.post("/api/v1/quizzes/generation-tasks", json=payload("request_task_0002"))).status_code == 409
        assert (await api.post("/api/v1/quizzes/generation-tasks", json=payload("request_task_0003", user_input="赌博教程"))).status_code == 400
    async with task_env[0]() as db:
        assert await db.scalar(select(func.count()).select_from(QuizGenerationTask)) == 1


@pytest.mark.parametrize("status", ["success", "fallback", "disabled"])
async def test_task_search_path_and_source_privacy(task_env, status):
    sessions, _, _, _ = task_env
    config = search_settings(ENABLE_WEB_SEARCH=True)
    provider = Provider(search_response("RAG 检索增强生成") if status == "success" else {"error": "Error 401"})
    search = WebSearchService(config, provider)
    runner = QuizTaskWorker(sessions, config, lambda: EnhancedGenerator(), lambda: search)
    async with client() as api:
        task = (await api.post("/api/v1/quizzes/generation-tasks", json=payload(user_input="RAG 检索增强生成", enable_web_search=status != "disabled"))).json()["data"]
        await runner.run_once()
        result = (await api.get(f"/api/v1/quizzes/generation-tasks/{task['task_id']}")).json()["data"]["result"]
        assert result["web_search"]["status"] == status
        assert result["web_search"]["sources"] == []
        assert all("answer" not in question and "explanation" not in question for question in result["questions"])
    async with sessions() as db:
        saved = await db.scalar(select(Quiz).where(Quiz.public_id == result["quiz_id"]))
        assert bool(saved.web_search_metadata_json["sources"]) == (status == "success")
    assert len(provider.calls) == (0 if status == "disabled" else 1)


async def test_two_workers_claim_only_once_and_queue_survives_restart(task_env):
    async with client() as api:
        task = (await api.post("/api/v1/quizzes/generation-tasks", json=payload())).json()["data"]
    generator = Generator()
    first, restarted = worker(task_env, generator), worker(task_env, generator)
    claims = await asyncio.gather(first.claim(), restarted.claim())
    claimed = [c for c in claims if c is not None]
    assert len(claimed) == 1
    await restarted.execute(claimed[0])
    async with client() as api:
        assert (await api.get(f"/api/v1/quizzes/generation-tasks/{task['task_id']}")).json()["data"]["status"] == "succeeded"
    assert generator.calls == 1


@pytest.mark.parametrize("kind", ["generation", "timeout", "persistence"])
async def test_failure_persists_and_rolls_back_all_result_rows(task_env, monkeypatch, kind):
    async with client() as api:
        task = (await api.post("/api/v1/quizzes/generation-tasks", json=payload())).json()["data"]
    generator = Generator(broken=kind == "generation", blocked=kind == "timeout")
    runner = worker(task_env, generator)
    if kind == "timeout":
        runner.settings = runner.settings.model_copy(update={"quiz_task_timeout_seconds": 0.02})
    if kind == "persistence":
        async def broken_save(*args, **kwargs):
            raise RuntimeError("database failure")
        monkeypatch.setattr(LearningService, "create_attempt", broken_save)
    await runner.run_once()
    async with client() as api:
        state = (await api.get(f"/api/v1/quizzes/generation-tasks/{task['task_id']}")).json()["data"]
        assert state["status"] == "failed" and state["result"] is None
        assert "secret" not in str(state)
        if kind == "timeout":
            assert state["error"]["code"] == "task_timeout"
    async with task_env[0]() as db:
        for model in (Quiz, Question, LearningAttempt):
            assert await db.scalar(select(func.count()).select_from(model)) == 0


async def test_expired_running_task_cannot_publish_late_result(task_env):
    async with client() as api:
        task = (await api.post("/api/v1/quizzes/generation-tasks", json=payload())).json()["data"]
    generator = Generator(blocked=True)
    runner = worker(task_env, generator)
    operation = asyncio.create_task(runner.run_once())
    await asyncio.wait_for(generator.entered.wait(), 1)
    async with task_env[0]() as db:
        await db.execute(update(QuizGenerationTask).values(lease_expires_at=utc_now()-timedelta(seconds=1)))
        await db.commit()
    await worker(task_env, Generator()).expire_stale()
    generator.release.set()
    await operation
    async with client() as api:
        state = (await api.get(f"/api/v1/quizzes/generation-tasks/{task['task_id']}")).json()["data"]
        assert state["status"] == "failed" and state["error"]["code"] == "worker_interrupted"
    async with task_env[0]() as db:
        assert await db.scalar(select(func.count()).select_from(Quiz)) == 0


async def test_expired_queue_is_failed_without_calling_model(task_env):
    async with client() as api:
        task = (await api.post("/api/v1/quizzes/generation-tasks", json=payload())).json()["data"]
    async with task_env[0]() as db:
        await db.execute(update(QuizGenerationTask).values(created_at=utc_now()-timedelta(seconds=601)))
        await db.commit()
    generator = Generator()
    assert not await worker(task_env, generator).run_once()
    assert generator.calls == 0
    async with client() as api:
        assert (await api.get(f"/api/v1/quizzes/generation-tasks/{task['task_id']}")).json()["data"]["error"]["code"] == "queue_timeout"


async def test_worker_lifecycle_shutdown_marks_running_job_failed(task_env):
    async with client() as api:
        task = (await api.post("/api/v1/quizzes/generation-tasks", json=payload())).json()["data"]
    generator = Generator(blocked=True)
    runner = worker(task_env, generator)
    runner.start()
    await asyncio.wait_for(generator.entered.wait(), 1)
    await runner.close()
    assert runner.runners == []
    async with client() as api:
        assert (await api.get(f"/api/v1/quizzes/generation-tasks/{task['task_id']}")).json()["data"]["error"]["code"] == "worker_interrupted"


async def test_app_lifespan_processes_task_after_creation_connection_closes(task_env, monkeypatch):
    import app.main as main
    generator = Generator(blocked=True)
    monkeypatch.setattr(main, "SessionLocal", task_env[0])
    monkeypatch.setattr(main, "get_settings", lambda: task_env[1])
    monkeypatch.setattr(main, "get_quiz_generator", lambda: generator)
    monkeypatch.setattr(main, "get_web_search_service", lambda: WebSearchService(task_env[1]))
    async with app.router.lifespan_context(app):
        async with client() as api:
            created = await api.post("/api/v1/quizzes/generation-tasks", json=payload())
            assert created.status_code == 202
            task_id = created.json()["data"]["task_id"]
        await asyncio.wait_for(generator.entered.wait(), 1)
        generator.release.set()
        async with asyncio.timeout(1):
            async with client() as api:
                while True:
                    task = (await api.get(f"/api/v1/quizzes/generation-tasks/{task_id}")).json()["data"]
                    if task["status"] == "succeeded":
                        break
                    await asyncio.sleep(0.01)
        assert task["result"]["attempt_id"]


async def test_worker_loop_recovers_from_database_error_and_logging_failure(monkeypatch):
    config = Settings(_env_file=None, QUIZ_TASK_WORKERS=1, QUIZ_TASK_POLL_SECONDS=0.001)
    runner = QuizTaskWorker(None, config, None, None)
    recovered = asyncio.Event()
    calls = 0
    async def run_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database temporarily unavailable")
        recovered.set()
        return False
    def broken_log(*args):
        raise RuntimeError("logging failed")
    monkeypatch.setattr(runner, "run_once", run_once)
    monkeypatch.setattr("app.services.quiz_task_service.logger.warning", broken_log)
    runner.start()
    await asyncio.wait_for(recovered.wait(), 1)
    await runner.close()
    assert calls >= 2


async def test_quiz_task_migration_is_additive_and_repeatable(task_env):
    path = Path(__file__).parents[1] / "alembic/versions/20261003_0003_quiz_tasks.py"
    spec = importlib.util.spec_from_file_location("quiz_tasks_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    async with task_env[0]() as db:
        connection = await db.connection()
        def exercise(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration.downgrade()
                assert "quiz_generation_tasks" not in inspect(sync_connection).get_table_names()
                migration.upgrade()
                migration.upgrade()
                assert "quiz_generation_tasks" in inspect(sync_connection).get_table_names()
        await connection.run_sync(exercise)
        assert await db.scalar(select(func.count()).select_from(User)) == 2
