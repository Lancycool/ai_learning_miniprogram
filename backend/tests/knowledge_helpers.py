"""MySQL-only fixtures; fail before any destructive test setup on a real database."""

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.models import User


async def make_knowledge_env(tmp_path):
    configured = get_settings()
    url = make_url(configured.test_database_url)
    assert url.get_backend_name() == "mysql"
    assert url.database and url.database.endswith("_test")
    assert url != make_url(configured.database_url)
    engine = create_async_engine(configured.test_database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(_env_file=None, ENABLE_KNOWLEDGE_BASE=True, ENABLE_WEB_SEARCH=False,
                        KNOWLEDGE_STORAGE_DIRECTORY=str(tmp_path / "knowledge"),
                        CHROMA_PERSIST_DIRECTORY=str(tmp_path / "chroma"))
    async with sessions() as db:
        user, other = User(public_id="usr-kb-owner"), User(public_id="usr-kb-other")
        db.add_all([user, other])
        await db.commit()
    return engine, sessions, settings, user, other
