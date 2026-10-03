from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AuthenticationError
from app.core.security import TokenService
from app.db.models import AuthSession, User
from app.llm.deepseek_generators import DeepSeekQuizGenerator, DeepSeekReportGenerator
from app.services.quiz_service import QuizGenerator
from app.services.report_service import ReportGenerator


@lru_cache
def get_quiz_generator() -> QuizGenerator:
    return DeepSeekQuizGenerator(get_settings())


@lru_cache
def get_report_generator() -> ReportGenerator:
    return DeepSeekReportGenerator(get_settings())


bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if not credentials:
        raise AuthenticationError()
    settings = get_settings()
    token_service = TokenService(settings.jwt_secret_key, settings.jwt_issuer, settings.jwt_audience, settings.access_token_expire_minutes, settings.refresh_token_expire_days)
    payload = token_service.decode_access_token(credentials.credentials)
    session = await db.scalar(select(AuthSession).where(AuthSession.public_id == payload["sid"], AuthSession.revoked_at.is_(None)))
    user = await db.scalar(select(User).where(User.public_id == payload["sub"], User.status == "active"))
    if not session or not user or session.user_id != user.id:
        raise AuthenticationError()
    return user
