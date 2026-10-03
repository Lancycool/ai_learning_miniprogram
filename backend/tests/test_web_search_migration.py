import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select

from app.db.models import Quiz, User
from tests.test_user_system_integration import db  # MySQL test database fixture


async def test_additive_search_migration_upgrade_and_downgrade(db):
    user = User(public_id="usr-migration")
    db.add(user)
    await db.flush()
    quiz = Quiz(public_id="quiz-migration", user_id=user.id, user_input="AI", title="AI", summary="旧题库内容", question_count=3)
    db.add(quiz)
    await db.commit()
    path = Path(__file__).parents[1] / "alembic/versions/20261003_0002_web_search.py"
    spec = importlib.util.spec_from_file_location("web_search_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = await db.connection()
    def exercise(sync_connection):
        with Operations.context(MigrationContext.configure(sync_connection)):
            migration.downgrade()
            assert "web_search_metadata_json" not in {c["name"] for c in inspect(sync_connection).get_columns("quizzes")}
            migration.upgrade()
            migration.upgrade()  # Fresh install and repeated upgrade are safe.
            column = next(c for c in inspect(sync_connection).get_columns("quizzes") if c["name"] == "web_search_metadata_json")
            assert column["nullable"] is True
    await connection.run_sync(exercise)
    db.expire_all()
    saved = await db.scalar(select(Quiz).where(Quiz.public_id == "quiz-migration"))
    assert saved.summary == "旧题库内容" and saved.web_search_metadata_json is None
