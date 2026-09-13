from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_quiz_generator
from app.core.config import get_settings
from app.models.common import ApiResponse
from app.models.quiz import Quiz, QuizGenerateRequest
from app.services.quiz_service import QuizGenerator, QuizService
from app.utils.content_filter import ContentFilter


router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.post("/generate", response_model=ApiResponse[Quiz])
async def generate_quiz(
    request: QuizGenerateRequest,
    generator: Annotated[QuizGenerator, Depends(get_quiz_generator)],
) -> ApiResponse[Quiz]:
    service = QuizService(generator, ContentFilter(get_settings().blocked_term_list))
    return ApiResponse(data=await service.generate(request))

