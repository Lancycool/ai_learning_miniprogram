import pytest
from pydantic import ValidationError

from app.models.quiz import AnswerRecord
from app.models.report import ReportGenerateRequest
from app.models.user_system import SubmitAnswerRequest


def original_report_question():
    return {"id": "original-report-one", "type": "multiple", "stem": "原文长题干" * 1000,
        "options": [{"key": chr(65+i), "text": f"完整选项{i}"} for i in range(6)],
        "answer": list("ABCDE"), "explanation": None, "knowledge_point": "原文流程", "difficulty": "medium"}


def test_private_report_accepts_one_long_original_and_more_than_four_answers():
    from app.models.private_learning import PrivateReportGenerateRequest, OriginalAnswerRecord
    request = PrivateReportGenerateRequest(quiz_id="private-quiz", topic="原题",
        questions=[original_report_question()], answer_records=[{"question_id": "original-report-one",
            "selected_answers": list("ABCDE"), "duration_ms": 1000}])
    assert len(request.questions[0].stem) == 5000 and len(request.answer_records[0].selected_answers) == 5
    from app.services.scoring_service import ScoringService
    scored = ScoringService().score(request.questions, request.answer_records)
    assert scored.accuracy == 100 and scored.total_count == 1
    SubmitAnswerRequest(question_id="q", selected_answers=list("ABCDE"), duration_ms=1000, idempotency_key="original-answer-0001")
    with pytest.raises(ValidationError):
        AnswerRecord(question_id="q", selected_answers=list("ABCDE"), duration_ms=1000)
    with pytest.raises(ValidationError):
        ReportGenerateRequest(quiz_id="private-quiz", topic="原题", questions=[original_report_question()], answer_records=[])
