"""Owned private resources and immutable original-question versions."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OwnedResourceMixin(TimestampMixin):
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


class KnowledgeBase(OwnedResourceMixin, Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (Index("ix_knowledge_bases_owner", "user_id", "deleted_at", "created_at"),)
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    cover: Mapped[str] = mapped_column(String(20), default="book", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(6))


class KnowledgeDocument(OwnedResourceMixin, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (Index("ix_knowledge_documents_owner", "user_id", "knowledge_base_id", "deleted_at"),)
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    current_version_id: Mapped[int | None] = mapped_column(ForeignKey(
        "knowledge_document_versions.id", name="fk_document_current_version", use_alter=True, ondelete="SET NULL"))
    parse_status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    index_status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    cleanup_status: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(6))


class KnowledgeDocumentVersion(OwnedResourceMixin, Base):
    __tablename__ = "knowledge_document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_no", name="uq_knowledge_version_number"),)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    parsed_key: Mapped[str | None] = mapped_column(String(255))
    text_length: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parse_warnings_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    index_generation: Mapped[str | None] = mapped_column(String(40))
    embedding_fingerprint: Mapped[str | None] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class KnowledgeChapter(OwnedResourceMixin, Base):
    __tablename__ = "knowledge_chapters"
    __table_args__ = (
        UniqueConstraint("version_id", "sequence_no", name="uq_knowledge_chapter_sequence"),
        CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="ck_chapter_offsets"),
    )
    version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_public_id: Mapped[str | None] = mapped_column(String(40))
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)


class KnowledgeProcessingTask(OwnedResourceMixin, Base):
    __tablename__ = "knowledge_processing_tasks"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_knowledge_task_request"),
        Index("ix_knowledge_tasks_queue", "status", "created_at", "id"),
        Index("ix_knowledge_tasks_document", "document_id", "status"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_knowledge_task_status"),
    )
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_type: Mapped[str] = mapped_column(String(24), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    stage: Mapped[str] = mapped_column(String(24), default="queued", nullable=False)
    processed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_count: Mapped[int | None] = mapped_column(Integer)
    claim_token: Mapped[str | None] = mapped_column(String(40))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(6))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(6))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(6))
    result_json: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(200))


class QuestionImportDraft(OwnedResourceMixin, Base):
    __tablename__ = "question_import_drafts"
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    chapter_ids_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    items_json: Mapped[list] = mapped_column(JSON, nullable=False)
    coverage_json: Mapped[list] = mapped_column(JSON, nullable=False)
    issues_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    __mapper_args__ = {"version_id_col": revision}


class QuestionBank(OwnedResourceMixin, Base):
    __tablename__ = "question_banks"
    __table_args__ = (
        UniqueConstraint("draft_id", "draft_revision", name="uq_question_bank_draft_revision"),
        UniqueConstraint("user_id", "confirm_request_id", name="uq_question_bank_confirmation"),
    )
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"), nullable=False)
    draft_id: Mapped[int] = mapped_column(ForeignKey("question_import_drafts.id", ondelete="RESTRICT"), nullable=False)
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    confirm_request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)


class QuestionBankItem(OwnedResourceMixin, Base):
    __tablename__ = "question_bank_items"
    __table_args__ = (UniqueConstraint("bank_id", "sequence_no", name="uq_question_bank_item_sequence"),)
    bank_id: Mapped[int] = mapped_column(ForeignKey("question_banks.id", ondelete="CASCADE"), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_id: Mapped[str | None] = mapped_column(String(40))
    question_type: Mapped[str] = mapped_column(String(16), nullable=False)
    stem: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    options_json: Mapped[list] = mapped_column(JSON, nullable=False)
    answer_json: Mapped[list] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str | None] = mapped_column(MEDIUMTEXT)
    source_json: Mapped[dict] = mapped_column(JSON, nullable=False)


class QuestionPracticeGroup(OwnedResourceMixin, Base):
    __tablename__ = "question_practice_groups"
    __table_args__ = (UniqueConstraint("bank_id", "scope_hash", "group_index", name="uq_question_practice_scope"),)
    bank_id: Mapped[int] = mapped_column(ForeignKey("question_banks.id", ondelete="CASCADE"), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chapter_ids_json: Mapped[list] = mapped_column(JSON, nullable=False)
    group_index: Mapped[int] = mapped_column(Integer, nullable=False)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="RESTRICT"), nullable=False)


class KnowledgeRetrievalTrace(TimestampMixin, Base):
    __tablename__ = "knowledge_retrieval_traces"
    __table_args__ = (
        UniqueConstraint("task_public_id", name="uq_knowledge_trace_task"),
        Index("ix_knowledge_trace_created", "created_at"),
        Index("ix_knowledge_trace_document", "document_public_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    task_public_id: Mapped[str] = mapped_column(String(40), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    knowledge_base_id: Mapped[str | None] = mapped_column(String(40))
    document_public_id: Mapped[str | None] = mapped_column(String(40))
    version_public_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    query_text: Mapped[str | None] = mapped_column(Text)
    retrieval_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    agent_events_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    selected_source_ids_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    validation_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    timings_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(200))


class KnowledgeBadCase(TimestampMixin, Base):
    __tablename__ = "knowledge_bad_cases"
    __table_args__ = (
        Index("ix_knowledge_bad_case_status", "status", "created_at"),
        Index("ix_knowledge_bad_case_type", "case_type", "created_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    trace_id: Mapped[int] = mapped_column(ForeignKey("knowledge_retrieval_traces.id", ondelete="CASCADE"), nullable=False)
    case_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
