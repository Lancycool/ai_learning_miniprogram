from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.web_search import WebSearchMetadata


class QuestionType(StrEnum):
    SINGLE = "single"
    MULTIPLE = "multiple"
    JUDGE = "judge"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Option(BaseModel):
    key: str = Field(min_length=1, max_length=4, pattern=r"^[A-Z]$")
    text: str = Field(min_length=1, max_length=160)

    @field_validator("key", "text", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class Question(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    id: str = Field(min_length=1, max_length=40)
    type: QuestionType
    stem: str = Field(min_length=2, max_length=500)
    options: list[Option] = Field(min_length=2, max_length=4)
    answer: list[str] = Field(min_length=1, max_length=4)
    explanation: str = Field(min_length=4, max_length=1200)
    knowledge_point: str = Field(min_length=1, max_length=80)
    difficulty: Difficulty

    @field_validator("id", "stem", "explanation", "knowledge_point", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("answer", mode="before")
    @classmethod
    def normalize_answers(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value]

    @model_validator(mode="after")
    def validate_contract(self) -> "Question":
        option_keys = [option.key for option in self.options]
        if len(option_keys) != len(set(option_keys)):
            raise ValueError("选项标识不能重复")
        if len(self.answer) != len(set(self.answer)):
            raise ValueError("答案不能重复")
        if not set(self.answer).issubset(option_keys):
            raise ValueError("答案必须存在于选项中")
        if self.type in {QuestionType.SINGLE, QuestionType.JUDGE} and len(self.answer) != 1:
            raise ValueError("单选题和判断题只能有一个答案")
        if self.type == QuestionType.MULTIPLE and len(self.answer) < 2:
            raise ValueError("多选题至少有两个答案")
        if self.type == QuestionType.JUDGE and len(self.options) != 2:
            raise ValueError("判断题必须有两个选项")
        return self


class QuizGenerateRequest(BaseModel):
    user_input: str = Field(min_length=2, max_length=2000)
    question_count: int = Field(default=5, ge=3, le=5)
    difficulty: str = Field(default="mixed", pattern=r"^(easy|mixed|hard)$")
    enable_web_search: bool | None = None

    @field_validator("user_input", mode="before")
    @classmethod
    def strip_user_input(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class QuizDraft(BaseModel):
    title: str = Field(min_length=2, max_length=80)
    summary: str = Field(min_length=4, max_length=300)
    questions: list[Question] = Field(min_length=3, max_length=5)


class Quiz(QuizDraft):
    quiz_id: str
    user_input: str
    web_search: WebSearchMetadata | None = None


class AnswerRecord(BaseModel):
    question_id: str = Field(min_length=1, max_length=40)
    selected_answers: list[str] = Field(min_length=1, max_length=4)
    is_correct: bool | None = None
    duration_ms: int = Field(ge=0, le=3_600_000)

    @field_validator("selected_answers", mode="before")
    @classmethod
    def normalize_answers(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value]


class ScoreSummary(BaseModel):
    correct_count: int
    total_count: int
    accuracy: int
    earned_xp: int
    mastered_points: list[str]
    weak_points: list[str]
    answer_records: list[AnswerRecord]
