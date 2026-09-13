from functools import lru_cache

from app.core.config import get_settings
from app.llm.deepseek_generators import DeepSeekQuizGenerator, DeepSeekReportGenerator
from app.services.quiz_service import QuizGenerator
from app.services.report_service import ReportGenerator


@lru_cache
def get_quiz_generator() -> QuizGenerator:
    return DeepSeekQuizGenerator(get_settings())


@lru_cache
def get_report_generator() -> ReportGenerator:
    return DeepSeekReportGenerator(get_settings())

