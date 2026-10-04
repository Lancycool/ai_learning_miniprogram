from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.quiz import QuestionType


class KnowledgeBaseInput(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    description: str = Field(default="", max_length=300)
    cover: Literal["book", "bamboo", "brain", "light"] = "book"

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class KnowledgeBasePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=30)
    description: str | None = Field(default=None, max_length=300)
    cover: Literal["book", "bamboo", "brain", "light"] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class KnowledgeRequest(BaseModel):
    request_id: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


class TextDocumentInput(KnowledgeRequest):
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=500000)


class DocumentSelection(BaseModel):
    document_id: str = Field(min_length=1, max_length=40)
    version_id: str = Field(min_length=1, max_length=40)
    chapter_ids: list[str] | None = Field(default=None, min_length=1, max_length=1000)


class KnowledgeScope(BaseModel):
    knowledge_base_id: str = Field(min_length=1, max_length=40)
    documents: list[DocumentSelection] = Field(min_length=1, max_length=20)


class ChapterInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    level: int = Field(default=1, ge=1, le=6)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)


class ChaptersPatch(BaseModel):
    version_id: str = Field(min_length=1, max_length=40)
    chapters: list[ChapterInput] = Field(min_length=1, max_length=1000)


class ImportTaskInput(KnowledgeRequest):
    version_id: str = Field(min_length=1, max_length=40)
    chapter_ids: list[str] | None = Field(default=None, min_length=1, max_length=1000)


class OriginalOption(BaseModel):
    key: str = Field(pattern=r"^[A-Z]$")
    text: str = Field(min_length=1, max_length=8000)
    source_label: str | None = Field(default=None, max_length=40)

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value):
        if not value.strip():
            raise ValueError("选项不能为空")
        return value


class OriginalDraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=40)
    type: Literal["single", "multiple", "judge", "unknown", "unsupported"]
    stem: str = Field(max_length=32000)
    options: list[OriginalOption] = Field(default_factory=list, max_length=26)
    answer: list[str] = Field(default_factory=list, max_length=26)
    explanation: str | None = Field(default=None, max_length=32000)
    chapter_id: str | None = Field(default=None, max_length=40)
    source: dict = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list, max_length=20)
    excluded: bool = False
    manually_edited: bool = False


class OriginalQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    type: QuestionType
    stem: str = Field(min_length=2, max_length=32000)
    options: list[OriginalOption] = Field(min_length=2, max_length=26)
    answer: list[str] = Field(min_length=1, max_length=26)
    explanation: str | None = Field(default=None, max_length=32000)
    chapter_id: str | None = Field(default=None, max_length=40)
    source: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_original(self):
        keys = [o.key for o in self.options]
        if not self.stem.strip() or len(keys) != len(set(keys)):
            raise ValueError("原题正文或选项不正确")
        if len(self.answer) != len(set(self.answer)) or not set(self.answer).issubset(keys):
            raise ValueError("原答案不能重复且必须对应选项")
        if self.type in (QuestionType.SINGLE, QuestionType.JUDGE) and len(self.answer) != 1:
            raise ValueError("单选和判断原题只能有一个答案")
        if self.type == QuestionType.JUDGE and len(self.options) != 2:
            raise ValueError("判断原题需要两个选项")
        return self


class ImportDraftPatch(BaseModel):
    revision: int = Field(ge=1)
    items: list[OriginalDraftItem] = Field(min_length=1, max_length=1000)


class ImportConfirmInput(KnowledgeRequest):
    revision: int = Field(ge=1)


class OriginalPracticeInput(KnowledgeRequest):
    chapter_ids: list[str] | None = Field(default=None, min_length=1, max_length=1000)
    group_index: int = Field(default=0, ge=0)
