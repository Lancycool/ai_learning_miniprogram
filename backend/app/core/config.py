from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_key: str = Field(default="", alias="API_KEY")
    base_url: str = Field(default="https://api.deepseek.com", alias="BASE_URL")
    model: str = Field(default="deepseek-flash", alias="MODEL")
    request_timeout_seconds: float = Field(default=45, alias="REQUEST_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")
    enable_web_search: bool = Field(default=True, alias="ENABLE_WEB_SEARCH")
    tavily_api_key: SecretStr = Field(default=SecretStr(""), validation_alias=AliasChoices("TAVILYSEARCH_API_KEY", "TAVILY_API_KEY"))
    tavily_search_timeout_seconds: float = Field(default=10, gt=0, alias="TAVILY_SEARCH_TIMEOUT_SECONDS")
    tavily_fallback_timeout_seconds: float = Field(default=5, gt=0, alias="TAVILY_FALLBACK_TIMEOUT_SECONDS")
    tavily_search_budget_seconds: float = Field(default=20, gt=0, alias="TAVILY_SEARCH_BUDGET_SECONDS")
    tavily_max_retries: int = Field(default=1, ge=0, le=1, alias="TAVILY_MAX_RETRIES")
    tavily_max_concurrency: int = Field(default=4, ge=1, alias="TAVILY_MAX_CONCURRENCY")
    tavily_queue_timeout_seconds: float = Field(default=1, gt=0, alias="TAVILY_QUEUE_TIMEOUT_SECONDS")
    tavily_circuit_failure_threshold: int = Field(default=5, ge=1, alias="TAVILY_CIRCUIT_FAILURE_THRESHOLD")
    tavily_circuit_cooldown_seconds: float = Field(default=30, gt=0, alias="TAVILY_CIRCUIT_COOLDOWN_SECONDS")
    quiz_generation_budget_seconds: float = Field(default=55, gt=0, alias="QUIZ_GENERATION_BUDGET_SECONDS")
    quiz_task_workers: int = Field(default=2, ge=1, le=16, alias="QUIZ_TASK_WORKERS")
    quiz_task_poll_seconds: float = Field(default=1, gt=0, alias="QUIZ_TASK_POLL_SECONDS")
    quiz_task_timeout_seconds: float = Field(default=90, gt=0, alias="QUIZ_TASK_TIMEOUT_SECONDS")
    quiz_task_queue_timeout_seconds: float = Field(default=600, gt=0, alias="QUIZ_TASK_QUEUE_TIMEOUT_SECONDS")
    blocked_terms: str = Field(
        default="赌博教程,毒品交易,制作炸弹",
        alias="BLOCKED_TERMS",
    )
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")
    database_url: str = Field(
        default="mysql+asyncmy://root:replace-with-local-password@localhost:3306/bamboo_quiz?charset=utf8mb4",
        alias="DATABASE_URL",
    )
    test_database_url: str = Field(
        default="mysql+asyncmy://root:replace-with-local-password@localhost:3306/bamboo_quiz_test?charset=utf8mb4",
        alias="TEST_DATABASE_URL",
    )
    wechat_app_id: str = Field(default="", alias="WECHAT_APP_ID")
    wechat_app_secret: str = Field(default="", alias="WECHAT_APP_SECRET")
    wechat_api_base_url: str = Field(default="https://api.weixin.qq.com", alias="WECHAT_API_BASE_URL")
    jwt_secret_key: str = Field(default="development-only-change-me", alias="JWT_SECRET_KEY")
    jwt_issuer: str = Field(default="bamboo-quiz-api", alias="JWT_ISSUER")
    jwt_audience: str = Field(default="bamboo-quiz-miniapp", alias="JWT_AUDIENCE")
    access_token_expire_minutes: int = Field(default=15, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=30, alias="REFRESH_TOKEN_EXPIRE_DAYS")
    avatar_storage_backend: str = Field(default="local", alias="AVATAR_STORAGE_BACKEND")
    avatar_local_directory: str = Field(default="./data/avatars", alias="AVATAR_LOCAL_DIRECTORY")

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def blocked_term_list(self) -> list[str]:
        return [item.strip() for item in self.blocked_terms.split(",") if item.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
