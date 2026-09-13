import pytest
from pydantic import ValidationError

from app.models.quiz import Difficulty, Option, Question, QuestionType, QuizGenerateRequest


def option(key: str) -> Option:
    return Option(key=key, text=f"选项 {key}")


def test_generate_request_strips_input() -> None:
    request = QuizGenerateRequest(user_input="  什么是 RAG？  ")
    assert request.user_input == "什么是 RAG？"
    assert request.question_count == 5
    assert request.difficulty == "mixed"


@pytest.mark.parametrize("value", ["", " ", "a", "x" * 2001])
def test_generate_request_rejects_invalid_input(value: str) -> None:
    with pytest.raises(ValidationError):
        QuizGenerateRequest(user_input=value)


def test_question_rejects_answer_outside_options() -> None:
    with pytest.raises(ValidationError):
        Question(
            id="q1",
            type=QuestionType.SINGLE,
            stem="RAG 的第一步是什么？",
            options=[option("A"), option("B")],
            answer=["C"],
            explanation="先检索相关资料。",
            knowledge_point="检索",
            difficulty=Difficulty.EASY,
        )


def test_multiple_question_requires_more_than_one_answer() -> None:
    with pytest.raises(ValidationError):
        Question(
            id="q1",
            type=QuestionType.MULTIPLE,
            stem="哪些说法正确？",
            options=[option("A"), option("B"), option("C")],
            answer=["A"],
            explanation="多选题至少有两个正确选项。",
            knowledge_point="基本概念",
            difficulty=Difficulty.MEDIUM,
        )


def test_judge_question_requires_two_options() -> None:
    with pytest.raises(ValidationError):
        Question(
            id="q1",
            type=QuestionType.JUDGE,
            stem="RAG 每次都会重新训练模型。",
            options=[option("A"), option("B"), option("C")],
            answer=["B"],
            explanation="RAG 会检索资料，不会每次重新训练模型。",
            knowledge_point="检索与训练",
            difficulty=Difficulty.EASY,
        )

