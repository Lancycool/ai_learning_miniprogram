from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class UserView(BaseModel):
    user_id: str
    nickname: str
    avatar_url: str
    profile_completed: bool
    xp_total: int
    current_streak_days: int
    joined_at: datetime


class WechatLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    access_token_expires_in: int
    refresh_token: str
    refresh_token_expires_in: int
    is_new_user: bool
    user: UserView


class UpdateProfileRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=24)

    @field_validator("nickname", mode="before")
    @classmethod
    def clean_nickname(cls, value: str) -> str:
        return " ".join(value.split()) if isinstance(value, str) else value


class CreateAttemptRequest(BaseModel):
    quiz_id: str | None = None
    attempt_type: str = Field(default="normal", pattern=r"^(normal|replay|review)$")


class SubmitAnswerRequest(BaseModel):
    question_id: str
    selected_answers: list[str] = Field(min_length=1, max_length=26)
    duration_ms: int = Field(ge=0, le=3_600_000)
    idempotency_key: str = Field(min_length=8, max_length=64)


class MonthlyReportQuery(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
