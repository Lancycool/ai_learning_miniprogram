from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import bearer
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AuthenticationError
from app.core.security import TokenService
from app.models.common import ApiResponse
from app.models.user_system import LoginResponse, RefreshRequest, WechatLoginRequest
from app.services.auth_service import AuthService


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/wechat-login", response_model=ApiResponse[LoginResponse])
async def wechat_login(request: WechatLoginRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[LoginResponse]:
    return ApiResponse(data=LoginResponse.model_validate(await AuthService(db, get_settings()).wechat_login(request.code)))


@router.post("/refresh", response_model=ApiResponse[LoginResponse])
async def refresh(request: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[LoginResponse]:
    return ApiResponse(data=LoginResponse.model_validate(await AuthService(db, get_settings()).refresh(request.refresh_token)))


@router.post("/logout", response_model=ApiResponse[dict[str, bool]])
async def logout(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[dict[str, bool]]:
    if not credentials:
        raise AuthenticationError()
    settings = get_settings()
    payload = TokenService(settings.jwt_secret_key, settings.jwt_issuer, settings.jwt_audience, settings.access_token_expire_minutes, settings.refresh_token_expire_days).decode_access_token(credentials.credentials)
    await AuthService(db, settings).logout(payload["sid"])
    return ApiResponse(data={"logged_out": True})
