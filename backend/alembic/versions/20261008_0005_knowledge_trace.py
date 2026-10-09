"""Store private retrieval diagnostics and maintenance bad cases."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261008_0005"
down_revision = "20261004_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("knowledge_retrieval_traces"):
        op.create_table(
            "knowledge_retrieval_traces",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=40), nullable=False),
        sa.Column("task_public_id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=40), nullable=True),
        sa.Column("document_public_id", sa.String(length=40), nullable=True),
        sa.Column("version_public_id", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=True),
        sa.Column("retrieval_json", sa.JSON(), nullable=False),
        sa.Column("agent_events_json", sa.JSON(), nullable=False),
        sa.Column("selected_source_ids_json", sa.JSON(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("timings_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=200), nullable=True),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("task_public_id", name="uq_knowledge_trace_task"),
        sa.Index("ix_knowledge_trace_created", "created_at"),
        sa.Index("ix_knowledge_trace_document", "document_public_id", "created_at"),
        )
    if not inspector.has_table("knowledge_bad_cases"):
        op.create_table(
            "knowledge_bad_cases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=40), nullable=False),
        sa.Column("trace_id", sa.BigInteger(), nullable=False),
        sa.Column("case_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["trace_id"], ["knowledge_retrieval_traces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.Index("ix_knowledge_bad_case_status", "status", "created_at"),
        sa.Index("ix_knowledge_bad_case_type", "case_type", "created_at"),
        )


def downgrade() -> None:
    op.drop_table("knowledge_bad_cases")
    op.drop_table("knowledge_retrieval_traces")
