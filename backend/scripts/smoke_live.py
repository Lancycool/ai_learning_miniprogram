"""使用当前 .env 对真实模型做一次最小端到端检查。"""

import asyncio
import json

from app.core.config import get_settings
from app.llm.deepseek_generators import DeepSeekQuizGenerator, DeepSeekReportGenerator
from app.models.quiz import AnswerRecord, QuizGenerateRequest
from app.models.report import ReportGenerateRequest
from app.services.quiz_service import QuizService
from app.services.report_service import ReportService
from app.services.scoring_service import ScoringService
from app.utils.content_filter import ContentFilter


async def main() -> None:
    settings = get_settings()
    quiz_service = QuizService(
        DeepSeekQuizGenerator(settings),
        ContentFilter(settings.blocked_term_list),
    )
    quiz = await quiz_service.generate(
        QuizGenerateRequest(user_input="光合作用基础知识", question_count=5)
    )
    records = [
        AnswerRecord(
            question_id=question.id,
            selected_answers=question.answer,
            duration_ms=1000,
        )
        for question in quiz.questions
    ]
    report_service = ReportService(
        DeepSeekReportGenerator(settings),
        ScoringService(),
    )
    report = await report_service.generate(
        ReportGenerateRequest(
            quiz_id=quiz.quiz_id,
            topic=quiz.title,
            questions=quiz.questions,
            answer_records=records,
        )
    )
    counts = {question_type: 0 for question_type in ("single", "multiple", "judge")}
    for question in quiz.questions:
        counts[question.type.value] += 1
    print(
        json.dumps(
            {
                "quiz_question_count": len(quiz.questions),
                "question_type_counts": counts,
                "report_accuracy": report.accuracy,
                "report_summary_count": len(report.three_line_summary),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
