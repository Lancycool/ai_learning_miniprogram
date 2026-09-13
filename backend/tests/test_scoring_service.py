import pytest

from app.core.exceptions import InvalidSubmissionError
from app.models.quiz import AnswerRecord, Difficulty, Option, Question, QuestionType
from app.services.scoring_service import ScoringService


def make_question(question_id: str, answer: list[str], kind: QuestionType) -> Question:
    return Question(
        id=question_id,
        type=kind,
        stem=f"题目 {question_id}",
        options=[Option(key=key, text=f"选项 {key}") for key in ["A", "B", "C", "D"]],
        answer=answer,
        explanation="这是一段讲解。",
        knowledge_point=f"知识点 {question_id}",
        difficulty=Difficulty.MEDIUM,
    )


def test_scoring_ignores_multiple_answer_order_and_frontend_flag() -> None:
    questions = [
        make_question("q1", ["A"], QuestionType.SINGLE),
        make_question("q2", ["A", "C"], QuestionType.MULTIPLE),
    ]
    records = [
        AnswerRecord(question_id="q1", selected_answers=["B"], is_correct=True, duration_ms=1200),
        AnswerRecord(question_id="q2", selected_answers=["C", "A"], is_correct=False, duration_ms=2300),
    ]

    result = ScoringService().score(questions, records)

    assert result.correct_count == 1
    assert result.total_count == 2
    assert result.accuracy == 50
    assert result.earned_xp == 20
    assert result.mastered_points == ["知识点 q2"]
    assert result.weak_points == ["知识点 q1"]
    assert [record.is_correct for record in result.answer_records] == [False, True]


def test_scoring_rejects_missing_or_duplicate_answers() -> None:
    questions = [make_question("q1", ["A"], QuestionType.SINGLE)]
    duplicate = [
        AnswerRecord(question_id="q1", selected_answers=["A"], duration_ms=100),
        AnswerRecord(question_id="q1", selected_answers=["A"], duration_ms=100),
    ]

    with pytest.raises(InvalidSubmissionError):
        ScoringService().score(questions, [])
    with pytest.raises(InvalidSubmissionError):
        ScoringService().score(questions, duplicate)


def test_scoring_rejects_unknown_selected_option() -> None:
    question = make_question("q1", ["A"], QuestionType.SINGLE)
    record = AnswerRecord(question_id="q1", selected_answers=["Z"], duration_ms=100)
    with pytest.raises(InvalidSubmissionError):
        ScoringService().score([question], [record])

