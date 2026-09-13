import json
from typing import Any

from langchain_deepseek import ChatDeepSeek

from app.core.config import Settings
from app.core.exceptions import GenerationError, ReportGenerationError
from app.models.quiz import QuizDraft, QuizGenerateRequest, ScoreSummary
from app.models.report import ReportGenerateRequest, ReportNarrative
from app.prompts.quiz_prompt import QUIZ_PROMPT
from app.prompts.report_prompt import REPORT_PROMPT


class DeepSeekQuizGenerator:
    def __init__(self, settings: Settings) -> None:
        self.max_attempts = max(1, settings.llm_max_retries + 1)
        model = ChatDeepSeek(
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url,
            temperature=0.4,
            timeout=settings.request_timeout_seconds,
            max_retries=0,
            reasoning_effort="none",
            max_tokens=5000,
        )
        prompt = QUIZ_PROMPT.partial(
            output_schema=json.dumps(QuizDraft.model_json_schema(), ensure_ascii=False)
        )
        self.chain = prompt | model.with_structured_output(
            QuizDraft,
            method="json_mode",
            include_raw=True,
        )

    async def generate(self, request: QuizGenerateRequest) -> QuizDraft:
        last_error: Exception | None = None
        for _ in range(self.max_attempts):
            try:
                result: dict[str, Any] = await self.chain.ainvoke(request.model_dump())
                if result.get("parsing_error") is not None or result.get("parsed") is None:
                    raise ValueError(
                        f"模型结构化输出解析失败: {result.get('parsing_error')!r}"
                    )
                return QuizDraft.model_validate(result["parsed"])
            except Exception as exc:
                last_error = exc
        raise GenerationError() from last_error


class DeepSeekReportGenerator:
    def __init__(self, settings: Settings) -> None:
        self.max_attempts = max(1, settings.llm_max_retries + 1)
        model = ChatDeepSeek(
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url,
            temperature=0.5,
            timeout=settings.request_timeout_seconds,
            max_retries=0,
            reasoning_effort="none",
            max_tokens=2200,
        )
        prompt = REPORT_PROMPT.partial(
            output_schema=json.dumps(ReportNarrative.model_json_schema(), ensure_ascii=False)
        )
        self.chain = prompt | model.with_structured_output(
            ReportNarrative,
            method="json_mode",
            include_raw=True,
        )

    async def generate(
        self,
        request: ReportGenerateRequest,
        score: ScoreSummary,
    ) -> ReportNarrative:
        record_by_question_id = {
            record.question_id: record for record in score.answer_records
        }
        details = [
            {
                "stem": question.stem,
                "knowledge_point": question.knowledge_point,
                "correct_answer": question.answer,
                "selected_answer": record_by_question_id[question.id].selected_answers,
                "is_correct": record_by_question_id[question.id].is_correct,
            }
            for question in request.questions
        ]
        payload = {
            "topic": request.topic,
            "accuracy": score.accuracy,
            "mastered_points": "、".join(score.mastered_points) or "暂无",
            "weak_points": "、".join(score.weak_points) or "暂无",
            "answer_details": json.dumps(details, ensure_ascii=False),
        }
        last_error: Exception | None = None
        for _ in range(self.max_attempts):
            try:
                result: dict[str, Any] = await self.chain.ainvoke(payload)
                if result.get("parsing_error") is not None or result.get("parsed") is None:
                    raise ValueError(
                        f"模型结构化输出解析失败: {result.get('parsing_error')!r}"
                    )
                return ReportNarrative.model_validate(result["parsed"])
            except Exception as exc:
                last_error = exc
        raise ReportGenerationError() from last_error
