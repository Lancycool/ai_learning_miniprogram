import pytest

from app.core.exceptions import GenerationError, ReportGenerationError
from app.models.quiz import (
    AnswerRecord,
    Difficulty,
    Option,
    Question,
    QuestionType,
    Quiz,
    QuizDraft,
    QuizGenerateRequest,
)
from app.models.report import ReportGenerateRequest, ReportNarrative
from app.services.quiz_service import QuizService
from app.services.report_service import ReportService
from app.services.scoring_service import ScoringService
from app.utils.content_filter import ContentFilter


def build_questions() -> list[Question]:
    kinds = [QuestionType.SINGLE] * 3 + [QuestionType.MULTIPLE, QuestionType.JUDGE]
    questions: list[Question] = []
    for index, kind in enumerate(kinds, start=1):
        options = [Option(key="A", text="正确说法"), Option(key="B", text="错误说法")]
        if kind != QuestionType.JUDGE:
            options += [Option(key="C", text="干扰项"), Option(key="D", text="干扰项")]
        questions.append(
            Question(
                id=f"q{index}",
                type=kind,
                stem=f"第 {index} 题",
                options=options,
                answer=["A", "C"] if kind == QuestionType.MULTIPLE else ["A"],
                explanation="这是一段清晰的讲解。",
                knowledge_point=f"知识点 {index}",
                difficulty=Difficulty.EASY,
            )
        )
    return questions


class FakeQuizGenerator:
    async def generate(self, request: QuizGenerateRequest) -> QuizDraft:
        return QuizDraft(title="RAG 入门闯关", summary="理解 RAG 的基本流程。", questions=build_questions())


class BrokenQuizGenerator:
    async def generate(self, request: QuizGenerateRequest) -> QuizDraft:  # type: ignore[name-defined]
        raise RuntimeError("provider failed")


class FakeReportGenerator:
    async def generate(self, request, score) -> ReportNarrative:  # type: ignore[no-untyped-def]
        return ReportNarrative(
            three_line_summary=["先检索资料。", "再生成答案。", "资料质量很重要。"],
            advice=["明天用自己的话解释一次。"],
            share_quote="知识需要一步一步走懂。",
        )


class BrokenReportGenerator:
    async def generate(self, request, score):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider failed")


@pytest.mark.asyncio
async def test_quiz_service_returns_valid_quiz() -> None:
    service = QuizService(FakeQuizGenerator(), ContentFilter(blocked_terms=[]))
    quiz = await service.generate(QuizGenerateRequest(user_input="什么是 RAG？"))
    assert quiz.quiz_id.startswith("quiz_")
    assert quiz.user_input == "什么是 RAG？"
    assert len(quiz.questions) == 5
    assert [question.type for question in quiz.questions].count(QuestionType.SINGLE) == 3


@pytest.mark.asyncio
async def test_quiz_service_wraps_provider_errors() -> None:
    service = QuizService(BrokenQuizGenerator(), ContentFilter(blocked_terms=[]))
    with pytest.raises(GenerationError):
        await service.generate(QuizGenerateRequest(user_input="什么是 RAG？"))


@pytest.mark.asyncio
async def test_report_service_uses_server_side_score() -> None:
    questions = build_questions()
    records = [
        AnswerRecord(question_id=q.id, selected_answers=q.answer if index < 4 else ["B"], duration_ms=1000)
        for index, q in enumerate(questions)
    ]
    request = ReportGenerateRequest(
        quiz_id="quiz_demo",
        topic="RAG 入门",
        questions=questions,
        answer_records=records,
    )
    report = await ReportService(FakeReportGenerator(), ScoringService()).generate(request)
    assert report.accuracy == 80
    assert report.correct_count == 4
    assert report.earned_xp == 18
    assert len(report.three_line_summary) == 3


@pytest.mark.asyncio
async def test_report_service_wraps_provider_errors() -> None:
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
    with pytest.raises(ReportGenerationError) as error:
        await ReportService(BrokenReportGenerator(), ScoringService()).generate(request)
    assert error.value.public_message == "复盘报告生成失败，请稍后重试"


@pytest.mark.asyncio
async def test_quiz_service_rejects_wrong_question_mix() -> None:
    class WrongMixGenerator:
        async def generate(self, request: QuizGenerateRequest) -> QuizDraft:
            questions = build_questions()
            questions[-1] = questions[0].model_copy(update={"id": "q5"})
            return QuizDraft(title="RAG 入门", summary="理解 RAG 的基本流程。", questions=questions)

    service = QuizService(WrongMixGenerator(), ContentFilter(blocked_terms=[]))
    with pytest.raises(GenerationError):
        await service.generate(QuizGenerateRequest(user_input="什么是 RAG？"))
