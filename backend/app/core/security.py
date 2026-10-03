import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt

from app.core.exceptions import AuthenticationError


class TokenService:
    def __init__(self, secret: str, issuer: str, audience: str, access_minutes: int, refresh_days: int) -> None:
        self.secret = secret
        self.issuer = issuer
        self.audience = audience
        self.access_minutes = access_minutes
        self.refresh_days = refresh_days

    def create_access_token(self, user_public_id: str, session_public_id: str) -> str:
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {"sub": user_public_id, "sid": session_public_id, "type": "access", "iat": now, "exp": now + timedelta(minutes=self.access_minutes), "jti": uuid4().hex, "iss": self.issuer, "aud": self.audience},
            self.secret,
            algorithm="HS256",
        )

    def decode_access_token(self, token: str) -> dict:
        try:
            payload = jwt.decode(token, self.secret, algorithms=["HS256"], issuer=self.issuer, audience=self.audience)
        except jwt.PyJWTError as exc:
            raise AuthenticationError() from exc
        if payload.get("type") != "access":
            raise AuthenticationError()
        return payload

    @staticmethod
    def create_refresh_token() -> str:
        return secrets.token_urlsafe(48)

    @staticmethod
    def hash_refresh_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def refresh_expires_at(self) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=self.refresh_days)
