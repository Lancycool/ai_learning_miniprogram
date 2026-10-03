import asyncio
import time
from typing import Protocol

from app.core.exceptions import AppError, GenerationError
from app.models.quiz import QuestionType, Quiz, QuizDraft, QuizGenerateRequest
from app.utils.content_filter import ContentFilter
from app.utils.id_generator import new_quiz_id
from app.core.config import Settings
from app.services.web_search_service import WebSearchService


class QuizGenerator(Protocol):
    async def generate(self, request: QuizGenerateRequest) -> QuizDraft: ...


class QuizService:
    def __init__(self, generator: QuizGenerator, content_filter: ContentFilter, search: WebSearchService | None = None, settings: Settings | None = None) -> None:
        self.generator = generator
        self.content_filter = content_filter
        self.search = search
        self.settings = settings

    async def generate(self, request: QuizGenerateRequest) -> Quiz:
        cleaned = self.content_filter.clean(request.user_input)
        clean_request = request.model_copy(update={"user_input": cleaned})
        quiz_id = new_quiz_id()
        metadata = None
        try:
            async with asyncio.timeout(self.settings.quiz_generation_budget_seconds if self.settings else None):
                context = None
                if self.search and self.settings:
                    metadata = await self.search.enrich(cleaned, request.enable_web_search, time.monotonic()+self.settings.quiz_generation_budget_seconds, quiz_id)
                    if metadata.context_used:
                        try:
                            context = "\n\n".join(f"[{s.source_id}] {s.title}\n{s.url}\n{s.content}" for s in metadata.sources)
                            if not context or len(context) > 6000:
                                raise ValueError("invalid context")
                            if not hasattr(self.generator, "generate_with_context"):
                                raise ValueError("generator has no enhancement support")
                        except Exception:
                            context = None
                            metadata.sources, metadata.context_used, metadata.status = [], False, "fallback"
                            metadata.fallback_reason, metadata.prompt_version = "context_error", "quiz_prompt_v1"
                            self.search.log(metadata, quiz_id, time.monotonic())
                if context is not None:
                    draft = await self.generator.generate_with_context(clean_request, context)
                else:
                    draft = await self.generator.generate(clean_request)
            self._validate_draft(draft, clean_request.question_count)
        except AppError:
            raise
        except Exception as exc:
            raise GenerationError() from exc
        return Quiz(
            quiz_id=quiz_id,
            user_input=cleaned,
            web_search=metadata,
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
