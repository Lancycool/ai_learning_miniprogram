from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_report_generator
from app.models.common import ApiResponse
from app.models.report import Report, ReportGenerateRequest
from app.services.report_service import ReportGenerator, ReportService
from app.services.scoring_service import ScoringService


router = APIRouter(prefix="/report", tags=["report"])


@router.post("/generate", response_model=ApiResponse[Report])
async def generate_report(
    request: ReportGenerateRequest,
    generator: Annotated[ReportGenerator, Depends(get_report_generator)],
) -> ApiResponse[Report]:
    service = ReportService(generator, ScoringService())
    return ApiResponse(data=await service.generate(request))

