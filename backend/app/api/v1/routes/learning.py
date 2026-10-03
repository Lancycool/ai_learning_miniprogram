from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_report_generator
from app.core.database import get_db
from app.db.models import AnswerRecord as DbAnswerRecord, AttemptQuestion, LearningAttempt, LearningReport, Question as DbQuestion, Quiz, User
from app.models.common import ApiResponse
from app.models.quiz import AnswerRecord, Difficulty, Option, Question, QuestionType
from app.models.report import ReportGenerateRequest
from app.models.user_system import CreateAttemptRequest, SubmitAnswerRequest
from app.services.learning_service import LearningService
from app.services.report_service import ReportGenerator, ReportService
from app.services.scoring_service import ScoringService
from sqlalchemy import select
from app.services.auth_service import public_id


router = APIRouter(tags=["learning"])


@router.post("/attempts", response_model=ApiResponse[dict])
async def create_attempt(request: CreateAttemptRequest, user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[dict]:
    if not request.quiz_id:
        from app.core.exceptions import ResourceNotFoundError
        raise ResourceNotFoundError("请选择题库")
    return ApiResponse(data=await LearningService(db).create_attempt(user, request.quiz_id, request.attempt_type))


@router.get("/attempts/{attempt_id}", response_model=ApiResponse[dict])
async def get_attempt(attempt_id: str, user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[dict]:
    return ApiResponse(data=await LearningService(db).get_attempt(user, attempt_id))


@router.post("/attempts/{attempt_id}/answers", response_model=ApiResponse[dict])
async def submit_answer(attempt_id: str, request: SubmitAnswerRequest, user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[dict]:
    return ApiResponse(data=await LearningService(db).submit_answer(user, attempt_id, request.question_id, request.selected_answers, request.duration_ms, request.idempotency_key))


@router.post("/attempts/{attempt_id}/complete", response_model=ApiResponse[dict])
async def complete(attempt_id: str, user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[dict]:
    return ApiResponse(data=await LearningService(db).complete(user, attempt_id))


@router.post("/attempts/{attempt_id}/report", response_model=ApiResponse[dict])
async def report(attempt_id: str, user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)], generator: Annotated[ReportGenerator, Depends(get_report_generator)]) -> ApiResponse[dict]:
    attempt = await db.scalar(select(LearningAttempt).where(LearningAttempt.public_id == attempt_id, LearningAttempt.user_id == user.id, LearningAttempt.status == "completed"))
    if not attempt:
        from app.core.exceptions import ResourceNotFoundError
        raise ResourceNotFoundError()
    saved = await db.scalar(select(LearningReport).where(LearningReport.attempt_id == attempt.id))
    if saved:
        return ApiResponse(data={"accuracy": attempt.accuracy, "correct_count": attempt.correct_count, "total_count": attempt.total_count, "earned_xp": attempt.earned_xp, "mastered_points": saved.mastered_points_json, "weak_points": saved.weak_points_json, "three_line_summary": saved.three_line_summary_json, "advice": saved.advice_json, "share_quote": saved.share_quote})
    quiz = await db.get(Quiz, attempt.quiz_id) if attempt.quiz_id else None
    rows = (await db.execute(select(DbQuestion, DbAnswerRecord).join(AttemptQuestion, AttemptQuestion.question_id == DbQuestion.id).join(DbAnswerRecord, (DbAnswerRecord.attempt_id == attempt.id) & (DbAnswerRecord.question_id == DbQuestion.id)).where(AttemptQuestion.attempt_id == attempt.id).order_by(AttemptQuestion.sequence_no))).all()
    request = ReportGenerateRequest(quiz_id=quiz.public_id if quiz else attempt.public_id, topic=quiz.title if quiz else "错题复习", questions=[Question(id=q.public_id, type=QuestionType(q.question_type), stem=q.stem, options=[Option.model_validate(x) for x in q.options_json], answer=q.answer_json, explanation=q.explanation, knowledge_point=q.knowledge_point, difficulty=Difficulty(q.difficulty)) for q, _ in rows], answer_records=[AnswerRecord(question_id=q.public_id, selected_answers=a.selected_answers_json, is_correct=a.is_correct, duration_ms=a.duration_ms) for q, a in rows])
    generated = await ReportService(generator, ScoringService()).generate(request)
    generated = generated.model_copy(update={"earned_xp": attempt.earned_xp})
    db.add(LearningReport(public_id=public_id("rpt"), attempt_id=attempt.id, mastered_points_json=generated.mastered_points, weak_points_json=generated.weak_points, three_line_summary_json=generated.three_line_summary, advice_json=generated.advice, share_quote=generated.share_quote, prompt_version="report_prompt_v1"))
    await db.commit()
    return ApiResponse(data=generated.model_dump())


@router.get("/learning/overview", response_model=ApiResponse[dict])
async def overview(user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[dict]:
    return ApiResponse(data=await LearningService(db).overview(user))


@router.get("/learning/history", response_model=ApiResponse[list[dict]])
async def history(user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)], status: str | None = None, keyword: str | None = None, limit: int = Query(20, ge=1, le=50)) -> ApiResponse[list[dict]]:
    return ApiResponse(data=await LearningService(db).history(user, status, keyword, limit))


@router.get("/learning/history/{attempt_id}", response_model=ApiResponse[dict])
async def history_detail(attempt_id: str, user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[dict]:
    return ApiResponse(data=await LearningService(db).get_attempt(user, attempt_id))


@router.get("/learning/monthly-report", response_model=ApiResponse[dict])
async def monthly(month: str, user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[dict]:
    return ApiResponse(data=await LearningService(db).monthly(user, month))


@router.get("/learning/garden", response_model=ApiResponse[list[dict]])
async def garden(user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[list[dict]]:
    return ApiResponse(data=await LearningService(db).garden(user))


@router.get("/mistakes", response_model=ApiResponse[dict])
async def mistakes(user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[dict]:
    return ApiResponse(data=await LearningService(db).mistakes(user))


@router.post("/reviews", response_model=ApiResponse[dict])
async def create_review(user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[dict]:
    return ApiResponse(data=await LearningService(db).create_review(user))
