from typing import Literal

from pydantic import BaseModel, Field


class SearchSource(BaseModel):
    source_id: str
    title: str
    url: str
    content: str
    published_at: str | None = None


class WebSearchMetadata(BaseModel):
    requested: bool
    enabled: bool
    status: Literal["success", "fallback", "disabled"]
    context_used: bool = False
    sources: list[SearchSource] = Field(default_factory=list)
    effective_params: dict = Field(default_factory=dict)
    attempt_count: int = 0
    fallback_reason: str | None = None
    prompt_version: str = "quiz_prompt_v1"


def search_view(metadata: dict | None, reveal: bool = False) -> dict | None:
    if metadata is None:
        return None
    value = WebSearchMetadata.model_validate(metadata).model_dump(mode="json")
    if not reveal:
        value["sources"] = []
    return value
