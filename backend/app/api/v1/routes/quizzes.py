from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_quiz_generator, get_web_search_service
from app.core.config import get_settings
from app.core.database import get_db
from app.db.models import User
from app.models.common import ApiResponse
from app.models.quiz import QuizGenerateRequest
from app.models.quiz_task import QuizTaskCreateRequest
from app.services.quiz_task_service import QuizTaskService
from app.services.quiz_persistence import save_generated_quiz
from app.services.learning_service import LearningService
from app.services.quiz_service import QuizGenerator, QuizService
from app.utils.content_filter import ContentFilter
from app.services.web_search_service import WebSearchService
from app.services.request_lifecycle import run_connected


router = APIRouter(prefix="/quizzes", tags=["quizzes"])


@router.post("/generation-tasks", response_model=ApiResponse[dict], status_code=202)
async def create_generation_task(request: QuizTaskCreateRequest, user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[dict]:
    return ApiResponse(data=await QuizTaskService(db, get_settings()).create(user, request))


@router.get("/generation-tasks/{task_id}", response_model=ApiResponse[dict])
async def get_generation_task(task_id: str, user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[dict]:
    return ApiResponse(data=await QuizTaskService(db, get_settings()).view(user, task_id))


@router.post("/generate", response_model=ApiResponse[dict])
async def generate(request: QuizGenerateRequest, http_request: Request, user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)], generator: Annotated[QuizGenerator, Depends(get_quiz_generator)], search: Annotated[WebSearchService, Depends(get_web_search_service)]) -> ApiResponse[dict]:
    settings = get_settings()
    generated = await run_connected(http_request, QuizService(generator, ContentFilter(settings.blocked_term_list), search, settings).generate(request))
    quiz = await save_generated_quiz(db, user.id, request, generated, settings)
    await db.commit()
    attempt = await LearningService(db).create_attempt(user, quiz.public_id)
    return ApiResponse(data={"quiz_id": quiz.public_id, "attempt_id": attempt["attempt_id"], "title": quiz.title, "summary": quiz.summary, "user_input": quiz.user_input, "questions": attempt["questions"], "web_search": attempt["web_search"]})
