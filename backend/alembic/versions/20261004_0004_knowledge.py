"""Add owned knowledge resources without erasing existing learning data."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import MEDIUMTEXT

from app.db.base import Base
from app.db import models  # noqa: F401

revision = "20261004_0004"
down_revision = "20261003_0003"
branch_labels = None
depends_on = None

TABLE_NAMES = {
    "knowledge_bases", "knowledge_documents", "knowledge_document_versions",
    "knowledge_chapters", "knowledge_processing_tasks", "question_import_drafts",
    "question_banks", "question_bank_items", "question_practice_groups",
}


def upgrade() -> None:
    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name in TABLE_NAMES:
            table.create(bind=bind, checkfirst=True)
    inspector = sa.inspect(bind)
    quiz_columns = {c["name"] for c in inspector.get_columns("quizzes")}
    if "knowledge_metadata_json" not in quiz_columns:
        op.add_column("quizzes", sa.Column("knowledge_metadata_json", sa.JSON(), nullable=True))
    columns = {c["name"]: c for c in inspector.get_columns("questions")}
    if "source_metadata_json" not in columns:
        op.add_column("questions", sa.Column("source_metadata_json", sa.JSON(), nullable=True))
    if "original_item_id" not in columns:
        op.add_column("questions", sa.Column("original_item_id", sa.BigInteger(), nullable=True))
    for field in ("stem", "explanation"):
        if not isinstance(columns[field]["type"], MEDIUMTEXT):
            op.alter_column("questions", field, existing_type=columns[field]["type"],
                            type_=MEDIUMTEXT(), existing_nullable=False)
    if not any("original_item_id" in f["constrained_columns"] for f in sa.inspect(bind).get_foreign_keys("questions")):
        op.create_foreign_key("fk_question_original_item", "questions", "question_bank_items",
                              ["original_item_id"], ["id"], ondelete="SET NULL")
    if not any("current_version_id" in f["constrained_columns"] for f in sa.inspect(bind).get_foreign_keys("knowledge_documents")):
        op.create_foreign_key("fk_document_current_version", "knowledge_documents", "knowledge_document_versions",
                              ["current_version_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    present = set(inspector.get_table_names())
    # Reject before making any DDL change. The normal rollback is the feature switch.
    for name in TABLE_NAMES & present:
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM `{name}`")).scalar():
            raise RuntimeError("系统需要保留私有资料；请先关闭功能并备份，不能自动删除数据")
    for name, column in (("quizzes", "knowledge_metadata_json"), ("questions", "source_metadata_json")):
        if column in {c["name"] for c in inspector.get_columns(name)}:
            if bind.execute(sa.text(f"SELECT COUNT(*) FROM `{name}` WHERE `{column}` IS NOT NULL")).scalar():
                raise RuntimeError("系统需要保留学习来源快照；请关闭功能并备份")
    for key in inspector.get_foreign_keys("questions"):
        if "original_item_id" in key["constrained_columns"]:
            op.drop_constraint(key["name"], "questions", type_="foreignkey")
    if "knowledge_documents" in present:
        for key in inspector.get_foreign_keys("knowledge_documents"):
            if "current_version_id" in key["constrained_columns"]:
                op.drop_constraint(key["name"], "knowledge_documents", type_="foreignkey")
    for name, column in (("questions", "original_item_id"), ("questions", "source_metadata_json"),
                          ("quizzes", "knowledge_metadata_json")):
        if column in {c["name"] for c in inspector.get_columns(name)}:
            op.drop_column(name, column)
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in TABLE_NAMES:
            table.drop(bind=bind, checkfirst=True)
    # Never shrink MEDIUMTEXT: legacy code can still read it, and long snapshots survive.
