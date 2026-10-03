"""Store optional search metadata on quizzes."""
from alembic import op
import sqlalchemy as sa

revision = "20261003_0002"
down_revision = "20260927_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial migration uses live ORM metadata; a fresh install already has
    # this column. Existing databases still need the additive migration.
    columns = sa.inspect(op.get_bind()).get_columns("quizzes")
    if "web_search_metadata_json" not in {column["name"] for column in columns}:
        op.add_column("quizzes", sa.Column("web_search_metadata_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("quizzes", "web_search_metadata_json")
