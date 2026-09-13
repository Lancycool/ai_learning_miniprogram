from typing import Protocol

from app.core.exceptions import AppError, ReportGenerationError
from app.models.quiz import ScoreSummary
from app.models.report import Report, ReportGenerateRequest, ReportNarrative
from app.services.scoring_service import ScoringService


class ReportGenerator(Protocol):
    async def generate(
        self,
        request: ReportGenerateRequest,
        score: ScoreSummary,
    ) -> ReportNarrative: ...


class ReportService:
    def __init__(self, generator: ReportGenerator, scoring: ScoringService) -> None:
        self.generator = generator
        self.scoring = scoring

    async def generate(self, request: ReportGenerateRequest) -> Report:
        score = self.scoring.score(request.questions, request.answer_records)
        try:
            narrative = await self.generator.generate(request, score)
        except AppError:
            raise
        except Exception as exc:
            raise ReportGenerationError() from exc
        return Report(
            accuracy=score.accuracy,
            correct_count=score.correct_count,
            total_count=score.total_count,
            earned_xp=score.earned_xp,
            mastered_points=score.mastered_points,
            weak_points=score.weak_points,
            **narrative.model_dump(),
        )

