from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_key: str = Field(alias="API_KEY")
    base_url: str = Field(default="https://api.deepseek.com", alias="BASE_URL")
    model: str = Field(default="deepseek-flash", alias="MODEL")
    request_timeout_seconds: float = Field(default=45, alias="REQUEST_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")
    blocked_terms: str = Field(
        default="赌博教程,毒品交易,制作炸弹",
        alias="BLOCKED_TERMS",
    )
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")

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

