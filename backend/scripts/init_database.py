import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.db import models  # noqa: F401


DOMAINS = [("ai", "人工智能", 10), ("science", "自然科学", 20), ("economics", "经济常识", 30), ("history", "历史文化", 40), ("language", "语言学习", 50), ("life", "生活常识", 60), ("other", "其他", 70)]


async def initialize(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        for code, name, order in DOMAINS:
            await connection.execute(text("INSERT INTO knowledge_domains (code, name, sort_order) VALUES (:code, :name, :sort_order) AS incoming ON DUPLICATE KEY UPDATE name=incoming.name, sort_order=incoming.sort_order"), {"code": code, "name": name, "sort_order": order})
    await engine.dispose()


async def main() -> None:
    settings = get_settings()
    await initialize(settings.database_url)
    await initialize(settings.test_database_url)


if __name__ == "__main__":
    asyncio.run(main())
