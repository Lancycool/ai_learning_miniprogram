from pydantic import BaseModel, Field, field_validator

from app.models.quiz import AnswerRecord, Question


class ReportGenerateRequest(BaseModel):
    quiz_id: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=2, max_length=200)
    questions: list[Question] = Field(min_length=3, max_length=5)
    answer_records: list[AnswerRecord]

    @field_validator("topic", mode="before")
    @classmethod
    def strip_topic(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class ReportNarrative(BaseModel):
    three_line_summary: list[str] = Field(min_length=3, max_length=3)
    advice: list[str] = Field(min_length=1, max_length=4)
    share_quote: str = Field(min_length=4, max_length=80)


class Report(ReportNarrative):
    accuracy: int = Field(ge=0, le=100)
    correct_count: int = Field(ge=0)
    total_count: int = Field(ge=1)
    earned_xp: int = Field(ge=0)
    mastered_points: list[str]
    weak_points: list[str]

