from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.mysql import MEDIUMTEXT

from app.db.base import Base, TimestampMixin, utc_now


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    nickname: Mapped[str] = mapped_column(String(24), default="竹岛学习者", nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(500), default="/assets/panda-logo.svg", nullable=False)
    profile_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    xp_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_streak_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    longest_streak_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_learning_date: Mapped[date | None] = mapped_column(Date)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(6))


class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider", "app_id", "provider_subject", name="uq_identity_provider_subject"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), default="wechat", nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(128, collation="utf8mb4_bin"), nullable=False)
    union_id: Mapped[str | None] = mapped_column(String(128))
    last_login_at: Mapped[datetime] = mapped_column(DateTime(6), default=utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), default=utc_now, nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_active", "user_id", "revoked_at", "expires_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(6))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(6))
    created_at: Mapped[datetime] = mapped_column(DateTime(6), default=utc_now, nullable=False)


class KnowledgeDomain(Base):
    __tablename__ = "knowledge_domains"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class Quiz(TimestampMixin, Base):
    __tablename__ = "quizzes"
    __table_args__ = (Index("ix_quizzes_user_created", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    domain_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_domains.id", ondelete="SET NULL"))
    source_type: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    user_input: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(16), default="mixed", nullable=False)
    generation_status: Mapped[str] = mapped_column(String(16), default="ready", nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    web_search_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    knowledge_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    questions: Mapped[list["Question"]] = relationship(back_populates="quiz", order_by="Question.sequence_no", cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("quiz_id", "sequence_no", name="uq_question_quiz_sequence"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    question_type: Mapped[str] = mapped_column(String(16), nullable=False)
    stem: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    options_json: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    answer_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    source_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    original_item_id: Mapped[int | None] = mapped_column(ForeignKey("question_bank_items.id", name="fk_question_original_item", ondelete="SET NULL"))
    knowledge_point: Mapped[str] = mapped_column(String(80), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), default=utc_now, nullable=False)
    quiz: Mapped[Quiz] = relationship(back_populates="questions")


class LearningAttempt(Base):
    __tablename__ = "learning_attempts"
    __table_args__ = (Index("ix_attempts_user_status_started", "user_id", "status", "started_at", "id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    quiz_id: Mapped[int | None] = mapped_column(ForeignKey("quizzes.id", ondelete="SET NULL"))
    attempt_type: Mapped[str] = mapped_column(String(16), default="normal", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="in_progress", nullable=False)
    current_sequence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    correct_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    accuracy: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    earned_xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_duration_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(6), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(6))
    abandoned_at: Mapped[datetime | None] = mapped_column(DateTime(6))


class QuizGenerationTask(TimestampMixin, Base):
    __tablename__ = "quiz_generation_tasks"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_quiz_task_request"),
        Index("ix_quiz_tasks_queue", "status", "created_at", "id"),
        Index("ix_quiz_tasks_user_status", "user_id", "status"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    claim_token: Mapped[str | None] = mapped_column(String(40))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(6))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(6))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(6))
    quiz_id: Mapped[int | None] = mapped_column(ForeignKey("quizzes.id", ondelete="SET NULL"))
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("learning_attempts.id", ondelete="SET NULL"))
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(200))


class AttemptQuestion(Base):
    __tablename__ = "attempt_questions"
    __table_args__ = (UniqueConstraint("attempt_id", "sequence_no", name="uq_attempt_question_sequence"),)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("learning_attempts.id", ondelete="CASCADE"), primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"), primary_key=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)


class AnswerRecord(Base):
    __tablename__ = "answer_records"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_answer_attempt_question"), UniqueConstraint("attempt_id", "idempotency_key", name="uq_answer_attempt_idempotency"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("learning_attempts.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False)
    selected_answers_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(6), default=utc_now, nullable=False)


class LearningReport(Base):
    __tablename__ = "learning_reports"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("learning_attempts.id", ondelete="CASCADE"), unique=True, nullable=False)
    mastered_points_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    weak_points_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    three_line_summary_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    advice_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    share_quote: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(6), default=utc_now, nullable=False)


class MistakeRecord(Base):
    __tablename__ = "mistake_records"
    __table_args__ = (UniqueConstraint("user_id", "question_id", name="uq_mistake_user_question"), Index("ix_mistakes_due", "user_id", "status", "next_review_at"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False)
    wrong_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    review_success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_stage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    first_wrong_at: Mapped[datetime] = mapped_column(DateTime(6), default=utc_now, nullable=False)
    last_wrong_at: Mapped[datetime] = mapped_column(DateTime(6), default=utc_now, nullable=False)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(6))
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(6))
    mastered_at: Mapped[datetime | None] = mapped_column(DateTime(6))


class XpTransaction(Base):
    __tablename__ = "xp_transactions"
    __table_args__ = (UniqueConstraint("user_id", "reason_type", "business_id", name="uq_xp_business"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_type: Mapped[str] = mapped_column(String(32), nullable=False)
    business_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), default=utc_now, nullable=False)


class UserDailyStat(Base):
    __tablename__ = "user_daily_stats"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    completed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    answered_questions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_answers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    learning_duration_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    earned_xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(6), default=utc_now, onupdate=utc_now, nullable=False)


class UserKnowledgeProgress(Base):
    __tablename__ = "user_knowledge_progress"
    __table_args__ = (UniqueConstraint("user_id", "domain_id", "knowledge_point", name="uq_user_domain_point"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    domain_id: Mapped[int] = mapped_column(ForeignKey("knowledge_domains.id", ondelete="RESTRICT"), nullable=False)
    knowledge_point: Mapped[str] = mapped_column(String(80), nullable=False)
    mastery: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="learning", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(6), default=utc_now, onupdate=utc_now, nullable=False)


# Keep the existing metadata import entry point for migrations and MySQL fixtures.
from app.db.knowledge_models import (  # noqa: E402,F401
    KnowledgeBase, KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeChapter,
    KnowledgeProcessingTask, QuestionImportDraft, QuestionBank, QuestionBankItem,
    QuestionPracticeGroup,
)
