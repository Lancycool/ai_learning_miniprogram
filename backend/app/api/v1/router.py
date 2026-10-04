from fastapi import APIRouter

from app.api.v1.routes import auth, health, learning, quiz, quizzes, report, users, knowledge


router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(quiz.router)
router.include_router(report.router)
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(quizzes.router)
router.include_router(learning.router)
router.include_router(knowledge.router)
