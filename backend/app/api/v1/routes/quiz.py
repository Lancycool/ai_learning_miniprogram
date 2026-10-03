from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_quiz_generator, get_web_search_service
from app.core.config import get_settings
from app.models.common import ApiResponse
from app.models.quiz import Quiz, QuizGenerateRequest
from app.services.quiz_service import QuizGenerator, QuizService
from app.utils.content_filter import ContentFilter
from app.services.web_search_service import WebSearchService
from app.services.request_lifecycle import run_connected


router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.post("/generate", response_model=ApiResponse[Quiz])
async def generate_quiz(
    request: QuizGenerateRequest,
    http_request: Request,
    generator: Annotated[QuizGenerator, Depends(get_quiz_generator)],
    search: Annotated[WebSearchService, Depends(get_web_search_service)],
) -> ApiResponse[Quiz]:
    settings = get_settings()
    service = QuizService(generator, ContentFilter(settings.blocked_term_list), search, settings)
    return ApiResponse(data=await run_connected(http_request, service.generate(request)))
