from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_quiz_generator
from app.core.config import get_settings
from app.core.database import get_db
from app.db.models import KnowledgeDomain, Question as DbQuestion, Quiz as DbQuiz, User
from app.models.common import ApiResponse
from app.models.quiz import QuizGenerateRequest
from app.services.auth_service import public_id
from app.services.quiz_service import QuizGenerator, QuizService
from app.utils.content_filter import ContentFilter


router = APIRouter(prefix="/quizzes", tags=["quizzes"])

DOMAIN_KEYWORDS = {"ai": ("AI", "人工智能", "RAG", "模型", "算法", "神经网络", "Transformer"), "science": ("科学", "物理", "化学", "生物", "天空", "光"), "economics": ("经济", "金融", "机会成本"), "history": ("历史", "文化"), "language": ("语言", "英语", "语法"), "life": ("生活", "咖啡", "健康")}


@router.post("/generate", response_model=ApiResponse[dict])
async def generate(request: QuizGenerateRequest, user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)], generator: Annotated[QuizGenerator, Depends(get_quiz_generator)]) -> ApiResponse[dict]:
    settings = get_settings()
    generated = await QuizService(generator, ContentFilter(settings.blocked_term_list)).generate(request)
    combined = f"{generated.title} {request.user_input}"
    code = next((name for name, keys in DOMAIN_KEYWORDS.items() if any(key.lower() in combined.lower() for key in keys)), "other")
    domain = await db.scalar(select(KnowledgeDomain).where(KnowledgeDomain.code == code))
    quiz = DbQuiz(public_id=generated.quiz_id, user_id=user.id, domain_id=domain.id if domain else None, user_input=generated.user_input, title=generated.title, summary=generated.summary, question_count=len(generated.questions), difficulty=request.difficulty, model_name=settings.model, prompt_version="quiz_prompt_v1")
    db.add(quiz)
    await db.flush()
    for sequence, item in enumerate(generated.questions, 1):
        db.add(DbQuestion(public_id=public_id("que"), quiz_id=quiz.id, sequence_no=sequence, question_type=item.type.value, stem=item.stem, options_json=[option.model_dump() for option in item.options], answer_json=item.answer, explanation=item.explanation, knowledge_point=item.knowledge_point, difficulty=item.difficulty.value))
    await db.commit()
    attempt = await __import__("app.services.learning_service", fromlist=["LearningService"]).LearningService(db).create_attempt(user, quiz.public_id)
    return ApiResponse(data={"quiz_id": quiz.public_id, "attempt_id": attempt["attempt_id"], "title": quiz.title, "summary": quiz.summary, "user_input": quiz.user_input, "questions": attempt["questions"]})
