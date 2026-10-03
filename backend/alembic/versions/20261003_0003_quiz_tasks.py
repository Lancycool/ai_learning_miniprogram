"""Add the durable quiz generation queue."""
from alembic import op

from app.db.models import QuizGenerationTask

revision = "20261003_0003"
down_revision = "20261003_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial migration also creates live ORM tables on a fresh install.
    QuizGenerationTask.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    QuizGenerationTask.__table__.drop(bind=op.get_bind(), checkfirst=True)
