"""Persist a generated quiz inside the caller's transaction."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import KnowledgeDomain, Question, Quiz
from app.models.quiz import Quiz as GeneratedQuiz, QuizGenerateRequest
from app.services.auth_service import public_id


DOMAIN_KEYWORDS = {"ai": ("AI", "人工智能", "RAG", "模型", "算法", "神经网络", "Transformer"), "science": ("科学", "物理", "化学", "生物", "天空", "光"), "economics": ("经济", "金融", "机会成本"), "history": ("历史", "文化"), "language": ("语言", "英语", "语法"), "life": ("生活", "咖啡", "健康")}


async def save_generated_quiz(db: AsyncSession, user_id: int, request: QuizGenerateRequest, generated: GeneratedQuiz, settings: Settings) -> Quiz:
    combined = f"{generated.title} {request.user_input}"
    code = next((name for name, keys in DOMAIN_KEYWORDS.items() if any(key.lower() in combined.lower() for key in keys)), "other")
    domain = await db.scalar(select(KnowledgeDomain).where(KnowledgeDomain.code == code))
    quiz = Quiz(public_id=generated.quiz_id, user_id=user_id, domain_id=domain.id if domain else None, user_input=generated.user_input, title=generated.title, summary=generated.summary, question_count=len(generated.questions), difficulty=request.difficulty, model_name=settings.model, prompt_version=generated.web_search.prompt_version if generated.web_search else "quiz_prompt_v1", web_search_metadata_json=generated.web_search.model_dump(mode="json") if generated.web_search else None)
    db.add(quiz)
    await db.flush()
    db.add_all([Question(public_id=public_id("que"), quiz_id=quiz.id, sequence_no=sequence, question_type=item.type.value, stem=item.stem, options_json=[option.model_dump() for option in item.options], answer_json=item.answer, explanation=item.explanation, knowledge_point=item.knowledge_point, difficulty=item.difficulty.value) for sequence, item in enumerate(generated.questions, 1)])
    await db.flush()
    return quiz
