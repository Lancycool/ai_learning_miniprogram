from pydantic import Field

from app.models.quiz import QuizGenerateRequest


class QuizTaskCreateRequest(QuizGenerateRequest):
    request_id: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
