"""Internal saved-learning report models; anonymous generation limits stay intact."""

from pydantic import Field

from app.models.knowledge import OriginalQuestion
from app.models.quiz import AnswerRecord, Difficulty
from app.models.report import ReportGenerateRequest


class OriginalAnswerRecord(AnswerRecord):
    selected_answers: list[str] = Field(min_length=1, max_length=26)


class PrivateReportQuestion(OriginalQuestion):
    knowledge_point: str = Field(min_length=1, max_length=80)
    difficulty: Difficulty


class PrivateReportGenerateRequest(ReportGenerateRequest):
    questions: list[PrivateReportQuestion] = Field(min_length=1, max_length=5)
    answer_records: list[OriginalAnswerRecord]
