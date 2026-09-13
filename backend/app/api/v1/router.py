from fastapi import APIRouter

from app.api.v1.routes import health, quiz, report


router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(quiz.router)
router.include_router(report.router)

