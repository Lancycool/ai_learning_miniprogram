import json

import pytest

from app.core.exceptions import GenerationError, ReportGenerationError
from app.llm.deepseek_generators import DeepSeekQuizGenerator, DeepSeekReportGenerator
from app.models.quiz import AnswerRecord, QuizDraft, QuizGenerateRequest
from app.models.report import ReportGenerateRequest, ReportNarrative
from app.prompts.quiz_prompt import QUIZ_PROMPT
from app.prompts.report_prompt import REPORT_PROMPT
from app.services.scoring_service import ScoringService
from tests.test_services import build_questions


class SequenceChain:
    def __init__(self, results):  # type: ignore[no-untyped-def]
        self.results = iter(results)
        self.payloads: list[dict] = []

    async def ainvoke(self, payload):  # type: ignore[no-untyped-def]
        self.payloads.append(payload)
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


def test_json_mode_prompts_request_the_exact_output_schema() -> None:
    assert "output_schema" in QUIZ_PROMPT.input_variables
    assert "output_schema" in REPORT_PROMPT.input_variables


@pytest.mark.asyncio
async def test_quiz_generator_retries_invalid_structure_then_succeeds() -> None:
    generator = DeepSeekQuizGenerator.__new__(DeepSeekQuizGenerator)
    generator.max_attempts = 2
    draft = QuizDraft(title="RAG 入门", summary="理解 RAG 的基本流程。", questions=build_questions())
    generator.chain = SequenceChain(
        [
            {"parsed": None, "parsing_error": ValueError("bad json")},
            {"parsed": draft, "parsing_error": None},
        ]
    )

    result = await generator.generate(QuizGenerateRequest(user_input="什么是 RAG？"))

    assert result.title == "RAG 入门"
    assert len(generator.chain.payloads) == 2


@pytest.mark.asyncio
async def test_quiz_generator_raises_public_error_after_all_attempts() -> None:
    generator = DeepSeekQuizGenerator.__new__(DeepSeekQuizGenerator)
    generator.max_attempts = 2
    generator.chain = SequenceChain([RuntimeError("one"), RuntimeError("two")])
    with pytest.raises(GenerationError):
        await generator.generate(QuizGenerateRequest(user_input="什么是 RAG？"))


@pytest.mark.asyncio
async def test_report_generator_matches_records_by_question_id() -> None:
    questions = build_questions()
    records = [
        AnswerRecord(question_id=q.id, selected_answers=q.answer, duration_ms=1000)
        for q in reversed(questions)
    ]
    request = ReportGenerateRequest(
        quiz_id="quiz_demo",
        topic="RAG 入门",
        questions=questions,
        answer_records=records,
    )
    score = ScoringService().score(questions, records)
    narrative = ReportNarrative(
        three_line_summary=["第一句。", "第二句。", "第三句。"],
        advice=["明天再解释一次。"],
        share_quote="一步一步走懂知识。",
    )
    generator = DeepSeekReportGenerator.__new__(DeepSeekReportGenerator)
    generator.max_attempts = 1
    generator.chain = SequenceChain([{"parsed": narrative, "parsing_error": None}])

    result = await generator.generate(request, score)

    payload = generator.chain.payloads[0]
    details = json.loads(payload["answer_details"])
    assert result == narrative
    assert all(item["correct_answer"] == item["selected_answer"] for item in details)


@pytest.mark.asyncio
async def test_report_generator_raises_public_error_on_parse_failure() -> None:
    questions = build_questions()
    records = [
        AnswerRecord(question_id=q.id, selected_answers=q.answer, duration_ms=1000)
        for q in questions
    ]
    request = ReportGenerateRequest(
        quiz_id="quiz_demo",
        topic="RAG 入门",
        questions=questions,
        answer_records=records,
    )
    score = ScoringService().score(questions, records)
    generator = DeepSeekReportGenerator.__new__(DeepSeekReportGenerator)
    generator.max_attempts = 1
    generator.chain = SequenceChain([{"parsed": None, "parsing_error": ValueError("bad") }])
    with pytest.raises(ReportGenerationError):
        await generator.generate(request, score)
