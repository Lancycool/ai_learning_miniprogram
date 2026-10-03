from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, RefreshTokenError
from app.core.security import TokenService
from app.db.base import utc_now
from app.db.models import AuthSession, User, UserIdentity
from app.integrations.wechat_client import WechatClient


def public_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:20]}"


class AuthService:
    def __init__(self, db: AsyncSession, settings: Settings, wechat: WechatClient | None = None) -> None:
        self.db = db
        self.settings = settings
        self.wechat = wechat or WechatClient(settings)
        self.tokens = TokenService(settings.jwt_secret_key, settings.jwt_issuer, settings.jwt_audience, settings.access_token_expire_minutes, settings.refresh_token_expire_days)

    async def wechat_login(self, code: str) -> dict:
        identity_data = await self.wechat.code_to_session(code)
        identity = await self.db.scalar(select(UserIdentity).where(UserIdentity.provider == "wechat", UserIdentity.app_id == self.settings.wechat_app_id, UserIdentity.provider_subject == identity_data["openid"]))
        is_new = identity is None
        if identity:
            user = await self.db.get(User, identity.user_id)
            identity.last_login_at = utc_now()
        else:
            user = User(public_id=public_id("usr"))
            self.db.add(user)
            await self.db.flush()
            self.db.add(UserIdentity(user_id=user.id, app_id=self.settings.wechat_app_id, provider_subject=identity_data["openid"], union_id=identity_data.get("unionid") or None))
        if user is None or user.status != "active":
            raise AuthenticationError("当前账号不可用")
        refresh = self.tokens.create_refresh_token()
        auth_session = AuthSession(public_id=public_id("ses"), user_id=user.id, refresh_token_hash=self.tokens.hash_refresh_token(refresh), expires_at=self.tokens.refresh_expires_at())
        self.db.add(auth_session)
        await self.db.commit()
        return self._login_payload(user, auth_session, refresh, is_new)

    async def refresh(self, raw_token: str) -> dict:
        now = utc_now()
        item = await self.db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == self.tokens.hash_refresh_token(raw_token)))
        if not item or item.revoked_at or item.expires_at <= now:
            raise RefreshTokenError()
        user = await self.db.get(User, item.user_id)
        if not user or user.status != "active":
            raise RefreshTokenError()
        refresh = self.tokens.create_refresh_token()
        item.refresh_token_hash = self.tokens.hash_refresh_token(refresh)
        item.last_used_at = now
        item.expires_at = self.tokens.refresh_expires_at()
        await self.db.commit()
        return self._login_payload(user, item, refresh, False)

    async def logout(self, session_public_id: str) -> None:
        item = await self.db.scalar(select(AuthSession).where(AuthSession.public_id == session_public_id))
        if item and not item.revoked_at:
            item.revoked_at = utc_now()
            await self.db.commit()

    def _login_payload(self, user: User, session: AuthSession, refresh: str, is_new: bool) -> dict:
        return {"access_token": self.tokens.create_access_token(user.public_id, session.public_id), "access_token_expires_in": self.settings.access_token_expire_minutes * 60, "refresh_token": refresh, "refresh_token_expires_in": self.settings.refresh_token_expire_days * 86400, "is_new_user": is_new, "user": user_to_dict(user)}


def user_to_dict(user: User) -> dict:
    return {"user_id": user.public_id, "nickname": user.nickname, "avatar_url": user.avatar_url, "profile_completed": user.profile_completed, "xp_total": user.xp_total, "current_streak_days": user.current_streak_days, "joined_at": user.created_at}
