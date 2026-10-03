from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base, utc_now
from app.db.models import KnowledgeDomain, MistakeRecord, Question, Quiz, User
from app.services.auth_service import AuthService, public_id
from app.services.learning_service import LearningService


class FakeWechat:
    def __init__(self, openid: str = "openid-user-a") -> None:
        self.openid = openid

    async def code_to_session(self, code: str) -> dict[str, str]:
        assert code
        return {"openid": self.openid, "unionid": ""}


@pytest.fixture
async def db():
    settings = get_settings()
    engine = create_async_engine(settings.test_database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_wechat_login_reuses_user_and_rotates_refresh_token(db) -> None:
    settings = get_settings()
    first = await AuthService(db, settings, FakeWechat()).wechat_login("code-1")
    second = await AuthService(db, settings, FakeWechat()).wechat_login("code-2")
    assert first["is_new_user"] is True
    assert second["is_new_user"] is False
    assert first["user"]["user_id"] == second["user"]["user_id"]
    refreshed = await AuthService(db, settings, FakeWechat()).refresh(second["refresh_token"])
    assert refreshed["refresh_token"] != second["refresh_token"]


async def test_answer_is_scored_on_server_and_completion_is_idempotent(db) -> None:
    user = User(public_id=public_id("usr"))
    domain = KnowledgeDomain(code="ai", name="人工智能", sort_order=10)
    db.add_all([user, domain])
    await db.flush()
    quiz = Quiz(public_id=public_id("quiz"), user_id=user.id, domain_id=domain.id, user_input="RAG", title="RAG", summary="summary", question_count=1)
    db.add(quiz)
    await db.flush()
    question = Question(public_id=public_id("que"), quiz_id=quiz.id, sequence_no=1, question_type="single", stem="正确答案？", options_json=[{"key": "A", "text": "A"}, {"key": "B", "text": "B"}], answer_json=["A"], explanation="因为 A 正确。", knowledge_point="RAG", difficulty="easy")
    db.add(question)
    await db.commit()
    service = LearningService(db)
    attempt = await service.create_attempt(user, quiz.public_id)
    result = await service.submit_answer(user, attempt["attempt_id"], question.public_id, ["A"], 1000, "idempotency-1")
    duplicate = await service.submit_answer(user, attempt["attempt_id"], question.public_id, ["B"], 1000, "idempotency-1")
    assert result["is_correct"] is True
    assert duplicate["is_correct"] is True
    completed = await service.complete(user, attempt["attempt_id"])
    again = await service.complete(user, attempt["attempt_id"])
    assert completed["earned_xp"] == 12
    assert again["xp_total"] == 12


async def test_wrong_answer_creates_due_review_and_review_advances_stage(db) -> None:
    user = User(public_id=public_id("usr"))
    domain = KnowledgeDomain(code="ai", name="人工智能", sort_order=10)
    db.add_all([user, domain])
    await db.flush()
    quiz = Quiz(public_id=public_id("quiz"), user_id=user.id, domain_id=domain.id, user_input="RAG", title="RAG", summary="summary", question_count=1)
    db.add(quiz)
    await db.flush()
    question = Question(public_id=public_id("que"), quiz_id=quiz.id, sequence_no=1, question_type="single", stem="正确答案？", options_json=[{"key": "A", "text": "A"}, {"key": "B", "text": "B"}], answer_json=["A"], explanation="因为 A 正确。", knowledge_point="RAG", difficulty="easy")
    db.add(question)
    await db.commit()
    service = LearningService(db)
    attempt = await service.create_attempt(user, quiz.public_id)
    await service.submit_answer(user, attempt["attempt_id"], question.public_id, ["B"], 1000, "idempotency-2")
    mistakes = await service.mistakes(user)
    assert mistakes["total"] == 1
    assert mistakes["items"][0]["wrong_count"] == 1
    record = await db.scalar(select(MistakeRecord).where(MistakeRecord.user_id == user.id))
    record.next_review_at = utc_now() - timedelta(seconds=1)
    await db.commit()
    review = await service.create_review(user)
    result = await service.submit_answer(user, review["attempt_id"], question.public_id, ["A"], 900, "review-answer-1")
    assert result["earned_xp_delta"] == 10
    await service.complete(user, review["attempt_id"])
    assert (await service.mistakes(user))["items"][0]["review_stage"] == 1
    assert len(await service.history(user, keyword="RAG")) == 1
    assert (await service.overview(user))["week_completed"] == 1
    month = datetime.now().strftime("%Y-%m")
    assert (await service.monthly(user, month))["completed_attempts"] == 1
    assert (await service.garden(user))[0]["knowledge_count"] == 1
