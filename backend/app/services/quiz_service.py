from typing import Protocol

from app.core.exceptions import AppError, GenerationError
from app.models.quiz import QuestionType, Quiz, QuizDraft, QuizGenerateRequest
from app.utils.content_filter import ContentFilter
from app.utils.id_generator import new_quiz_id


class QuizGenerator(Protocol):
    async def generate(self, request: QuizGenerateRequest) -> QuizDraft: ...


class QuizService:
    def __init__(self, generator: QuizGenerator, content_filter: ContentFilter) -> None:
        self.generator = generator
        self.content_filter = content_filter

    async def generate(self, request: QuizGenerateRequest) -> Quiz:
        cleaned = self.content_filter.clean(request.user_input)
        clean_request = request.model_copy(update={"user_input": cleaned})
        try:
            draft = await self.generator.generate(clean_request)
            self._validate_draft(draft, clean_request.question_count)
        except AppError:
            raise
        except Exception as exc:
            raise GenerationError() from exc
        return Quiz(
            quiz_id=new_quiz_id(),
            user_input=cleaned,
            **draft.model_dump(),
        )

    @staticmethod
    def _validate_draft(draft: QuizDraft, expected_count: int) -> None:
        if len(draft.questions) != expected_count:
            raise GenerationError("系统没有生成完整题目，请重试")
        ids = [question.id for question in draft.questions]
        if len(ids) != len(set(ids)):
            raise GenerationError("系统生成了重复题目，请重试")
        if expected_count == 5:
            counts = {kind: 0 for kind in QuestionType}
            for question in draft.questions:
                counts[question.type] += 1
            if counts != {
                QuestionType.SINGLE: 3,
                QuestionType.MULTIPLE: 1,
                QuestionType.JUDGE: 1,
            }:
                raise GenerationError("题型组成不完整，请重试")

