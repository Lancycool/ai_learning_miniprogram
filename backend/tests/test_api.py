from fastapi.testclient import TestClient

from app.api.dependencies import get_quiz_generator, get_report_generator
from app.main import app
from app.models.quiz import QuizDraft, QuizGenerateRequest
from app.models.report import ReportNarrative
from tests.test_services import build_questions


class FakeQuizGenerator:
    async def generate(self, request: QuizGenerateRequest) -> QuizDraft:
        return QuizDraft(title="RAG 入门闯关", summary="理解 RAG 的基本流程。", questions=build_questions())


class FakeReportGenerator:
    async def generate(self, request, score) -> ReportNarrative:  # type: ignore[no-untyped-def]
        return ReportNarrative(
            three_line_summary=["先检索资料。", "再生成答案。", "资料质量很重要。"],
            advice=["明天用自己的话解释一次。"],
            share_quote="知识需要一步一步走懂。",
        )


def client() -> TestClient:
    app.dependency_overrides[get_quiz_generator] = lambda: FakeQuizGenerator()
    app.dependency_overrides[get_report_generator] = lambda: FakeReportGenerator()
    return TestClient(app)


def test_health_api() -> None:
    response = client().get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"code": 0, "message": "ok", "data": {"status": "ok"}}


def test_quiz_generate_api() -> None:
    response = client().post("/api/v1/quiz/generate", json={"user_input": "什么是 RAG？"})
    body = response.json()
    assert response.status_code == 200
    assert body["code"] == 0
    assert len(body["data"]["questions"]) == 5


def test_quiz_generate_validation_error_uses_common_envelope() -> None:
    response = client().post("/api/v1/quiz/generate", json={"user_input": ""})
    assert response.status_code == 422
    assert response.json()["code"] == 4001
    assert response.json()["data"] is None


def test_report_generate_api_recomputes_accuracy() -> None:
    questions = [question.model_dump(mode="json") for question in build_questions()]
    records = [
        {
            "question_id": question["id"],
            "selected_answers": question["answer"] if index < 4 else ["B"],
            "is_correct": False,
            "duration_ms": 1000,
        }
        for index, question in enumerate(questions)
    ]
    response = client().post(
        "/api/v1/report/generate",
        json={
            "quiz_id": "quiz_demo",
            "topic": "RAG 入门",
            "questions": questions,
            "answer_records": records,
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["accuracy"] == 80


def test_report_generate_rejects_incomplete_answers() -> None:
    response = client().post(
        "/api/v1/report/generate",
        json={
            "quiz_id": "quiz_demo",
            "topic": "RAG 入门",
            "questions": [question.model_dump(mode="json") for question in build_questions()],
            "answer_records": [],
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == 4003

