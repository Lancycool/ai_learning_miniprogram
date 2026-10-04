from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.models.quiz import Question, Quiz, QuizDraft


class EvidenceCitation(BaseModel):
    source_id: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=2, max_length=1000)


class GroundedQuestion(Question):
    citations: list[EvidenceCitation] = Field(min_length=1, max_length=3)


class GroundedQuizDraft(QuizDraft):
    questions: list[GroundedQuestion] = Field(min_length=5, max_length=5)


class EvidenceSupport(BaseModel):
    supported: list[bool] = Field(min_length=5, max_length=5)
    private_rules_consistent: bool


@dataclass(frozen=True)
class KnowledgeGeneratedQuiz:
    quiz: Quiz
    snapshots: list[dict]
