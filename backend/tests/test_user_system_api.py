import asyncio
from io import BytesIO
from pathlib import Path
import shutil

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.dependencies import get_current_user, get_quiz_generator, get_report_generator
from app.core.config import get_settings
from app.core.database import get_db
from app.db.base import Base
from app.db.models import KnowledgeDomain, User
from app.main import app
from app.models.quiz import QuizDraft, QuizGenerateRequest
from app.models.report import ReportNarrative
from app.services.auth_service import public_id
from app.integrations.wechat_client import WechatClient
from PIL import Image
from tests.test_services import build_questions


class FakeQuizGenerator:
    async def generate(self, request: QuizGenerateRequest) -> QuizDraft:
        return QuizDraft(title="RAG 入门闯关", summary="理解检索增强生成。", questions=build_questions())


class FakeReportGenerator:
    async def generate(self, request, score):  # type: ignore[no-untyped-def]
        return ReportNarrative(three_line_summary=["先检索资料。", "再生成回答。", "资料质量很重要。"], advice=["明天再解释一次。"], share_quote="知识需要一步一步走懂。")


def test_authenticated_learning_api_flow() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.test_database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> User:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            user = User(public_id=public_id("usr"))
            session.add_all([user, KnowledgeDomain(code="ai", name="人工智能", sort_order=10), KnowledgeDomain(code="other", name="其他", sort_order=70)])
            await session.commit()
            return user

    user = asyncio.run(prepare())

    async def db_override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_quiz_generator] = lambda: FakeQuizGenerator()
    app.dependency_overrides[get_report_generator] = lambda: FakeReportGenerator()
    client = TestClient(app)
    generated = client.post("/api/v1/quizzes/generate", json={"user_input": "三分钟理解 RAG"})
    assert generated.status_code == 200
    quiz = generated.json()["data"]
    assert "answer" not in quiz["questions"][0]
    attempt_id = quiz["attempt_id"]
    answers = [question.answer for question in build_questions()]
    for index, (question, selected) in enumerate(zip(quiz["questions"], answers)):
        response = client.post(f"/api/v1/attempts/{attempt_id}/answers", json={"question_id": question["question_id"], "selected_answers": selected, "duration_ms": 1000, "idempotency_key": f"answer-key-{index}"})
        assert response.json()["data"]["is_correct"] is True
    completed = client.post(f"/api/v1/attempts/{attempt_id}/complete")
    assert completed.json()["data"]["earned_xp"] == 20
    assert client.post(f"/api/v1/attempts/{attempt_id}/complete").json()["data"]["xp_total"] == 20
    assert client.get(f"/api/v1/attempts/{attempt_id}").json()["data"]["status"] == "completed"
    assert len(client.get("/api/v1/learning/history").json()["data"]) == 1
    overview = client.get("/api/v1/learning/overview").json()["data"]
    assert overview["week_completed"] == 1
    assert overview["total_completed"] == 1
    assert overview["total_correct"] == 5
    assert overview["average_accuracy"] == 100
    assert len(overview["recent_history"]) == 1
    assert client.get("/api/v1/learning/garden").status_code == 200
    assert client.get("/api/v1/learning/monthly-report?month=2026-09").status_code == 200
    assert client.get("/api/v1/mistakes").json()["data"]["total"] == 0
    report = client.post(f"/api/v1/attempts/{attempt_id}/report")
    assert report.json()["data"]["accuracy"] == 100
    assert client.post(f"/api/v1/attempts/{attempt_id}/report").json()["data"]["share_quote"]
    replay = client.post("/api/v1/attempts", json={"quiz_id": quiz["quiz_id"], "attempt_type": "replay"})
    assert replay.json()["data"]["attempt_type"] == "replay"
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def test_auth_profile_refresh_avatar_and_logout_api(monkeypatch) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.test_database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
    asyncio.run(prepare())
    async def db_override():
        async with factory() as session:
            yield session
    async def fake_code(self, code: str) -> dict[str, str]:
        return {"openid": "api-openid", "unionid": ""}
    monkeypatch.setattr(WechatClient, "code_to_session", fake_code)
    import app.api.v1.routes.users as users_route
    avatar_temp = Path(__file__).parent / ".tmp_avatars"
    monkeypatch.setattr(users_route, "get_settings", lambda: settings.model_copy(update={"avatar_local_directory": str(avatar_temp)}))
    app.dependency_overrides[get_db] = db_override
    client = TestClient(app)
    login = client.post("/api/v1/auth/wechat-login", json={"code": "wx-code"}).json()["data"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    assert client.get("/api/v1/users/me", headers=headers).json()["data"]["nickname"] == "竹岛学习者"
    updated = client.patch("/api/v1/users/me", headers=headers, json={"nickname": "  青竹 学习者  "})
    assert updated.json()["data"]["nickname"] == "青竹 学习者"
    image = Image.new("RGB", (8, 8), "green")
    content = BytesIO(); image.save(content, "PNG")
    avatar = client.post("/api/v1/users/me/avatar", headers=headers, files={"file": ("avatar.png", content.getvalue(), "image/png")})
    assert avatar.json()["data"]["avatar_url"].endswith(".webp")
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}).json()["data"]
    assert refreshed["refresh_token"] != login["refresh_token"]
    new_headers = {"Authorization": f"Bearer {refreshed['access_token']}"}
    assert client.post("/api/v1/auth/logout", headers=new_headers).status_code == 200
    assert client.get("/api/v1/users/me", headers=new_headers).status_code == 401
    shutil.rmtree(avatar_temp, ignore_errors=True)
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())
