import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select, text

from app.db.base import Base
from app.db.models import KnowledgeBase, Quiz, User
from tests.test_knowledge_models import env


def migration_module():
    path = Path(__file__).parents[1] / "alembic/versions/20261004_0004_knowledge.py"
    spec = importlib.util.spec_from_file_location("knowledge_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_additive_migration_keeps_legacy_data_and_handles_repeated_upgrade(env):
    migration = migration_module()
    async with env[1]() as db:
        quiz = Quiz(public_id="quiz-old-migration", user_id=env[3].id, user_input="AI",
                    title="旧题库", summary="旧学习资料保持完整", question_count=5)
        db.add(quiz)
        await db.commit()
        connection = await db.connection()
        def exercise(conn):
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade()
                assert "knowledge_bases" not in inspect(conn).get_table_names()
                # Simulate the old widths without touching any real learning data.
                conn.execute(text("ALTER TABLE questions MODIFY stem VARCHAR(500) NOT NULL, MODIFY explanation VARCHAR(1200) NOT NULL"))
                migration.upgrade()
                migration.upgrade()
                columns = {c["name"]: c for c in inspect(conn).get_columns("questions")}
                assert str(columns["stem"]["type"]) == "MEDIUMTEXT"
                assert str(columns["explanation"]["type"]) == "MEDIUMTEXT"
                assert columns["source_metadata_json"]["nullable"] is True
                assert columns["original_item_id"]["nullable"] is True
                assert "fk_document_current_version" in {
                    c["name"] for c in inspect(conn).get_foreign_keys("knowledge_documents")}
        await connection.run_sync(exercise)
        db.expire_all()
        old = await db.scalar(select(Quiz).where(Quiz.public_id == "quiz-old-migration"))
        assert old.summary == "旧学习资料保持完整" and old.knowledge_metadata_json is None


async def test_downgrade_refuses_to_erase_private_data(env):
    migration = migration_module()
    async with env[1]() as db:
        db.add(KnowledgeBase(public_id="kb-do-not-delete", user_id=env[3].id, name="保留资料"))
        await db.commit()
        conn = await db.connection()
        def exercise(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                with pytest.raises(RuntimeError, match="保留"):
                    migration.downgrade()
                assert "knowledge_bases" in inspect(sync_connection).get_table_names()
        await conn.run_sync(exercise)
        assert (await db.scalar(select(KnowledgeBase))).name == "保留资料"


async def test_fresh_migration_chain_and_complete_sql_snapshot(env):
    backend = Path(__file__).parents[1]
    async with env[0].begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        def upgrade_chain(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                for name in ("20260927_0001_user_system.py", "20261003_0002_web_search.py",
                             "20261003_0003_quiz_tasks.py", "20261004_0004_knowledge.py",
                             "20261008_0005_knowledge_trace.py"):
                    spec = importlib.util.spec_from_file_location(name, backend / "alembic/versions" / name)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    module.upgrade()
                assert set(Base.metadata.tables).issubset(inspect(sync_connection).get_table_names())
        await conn.run_sync(upgrade_chain)
        snapshot = (backend / "sql/schema.sql").read_text(encoding="utf-8")
        for statement in snapshot.split(";"):
            if statement.strip():
                await conn.exec_driver_sql(statement)
        names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        assert set(Base.metadata.tables).issubset(names)
        columns = await conn.run_sync(lambda c: {v["name"] for v in inspect(c).get_columns("questions")})
        assert {"source_metadata_json", "original_item_id"}.issubset(columns)
