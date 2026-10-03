"""Read-only login diagnostics. Never print passwords, tokens or identities."""

import asyncio

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from asyncmy import auth as mysql_auth

from app.core.config import get_settings
from app.core.database import engine


async def main() -> None:
    settings = get_settings()
    url = make_url(settings.database_url)
    print({
        "database_host": url.host,
        "database_port": url.port,
        "database_name": url.database,
        "wechat_id_configured": bool(settings.wechat_app_id),
        "wechat_secret_configured": bool(settings.wechat_app_secret),
        "mysql_full_auth_supported": mysql_auth._have_cryptography,
    })
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
            print({"auth_tables": {name: name in tables for name in ("users", "user_identities", "auth_sessions")}})
            if "users" in tables:
                print({"user_count": await connection.scalar(text("SELECT COUNT(*) FROM users"))})
            if "auth_sessions" in tables:
                columns = await connection.run_sync(lambda sync: inspect(sync).get_columns("auth_sessions"))
                print({"auth_session_columns": [item["name"] for item in columns]})
    except (SQLAlchemyError, RuntimeError) as error:
        original = getattr(error, "orig", None)
        args = getattr(original, "args", ())
        print({"database_error": type(error).__name__, "mysql_error_code": args[0] if args else None})
        raise SystemExit(1) from None
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
