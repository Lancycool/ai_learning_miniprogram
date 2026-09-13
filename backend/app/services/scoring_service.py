from app.core.exceptions import InvalidSubmissionError
from app.models.quiz import AnswerRecord, Question, ScoreSummary


class ScoringService:
    def score(self, questions: list[Question], records: list[AnswerRecord]) -> ScoreSummary:
        question_by_id = {question.id: question for question in questions}
        record_ids = [record.question_id for record in records]
        if len(question_by_id) != len(questions):
            raise InvalidSubmissionError("题库包含重复题目")
        if len(record_ids) != len(set(record_ids)):
            raise InvalidSubmissionError("同一道题不能重复提交")
        if set(record_ids) != set(question_by_id):
            raise InvalidSubmissionError()

        evaluated: list[AnswerRecord] = []
        mastered: list[str] = []
        weak: list[str] = []
        correct_count = 0
        for record in records:
            question = question_by_id[record.question_id]
            option_keys = {option.key for option in question.options}
            if not set(record.selected_answers).issubset(option_keys):
                raise InvalidSubmissionError("答案包含不存在的选项")
            is_correct = set(record.selected_answers) == set(question.answer)
            correct_count += int(is_correct)
            (mastered if is_correct else weak).append(question.knowledge_point)
            evaluated.append(record.model_copy(update={"is_correct": is_correct}))

        total_count = len(questions)
        accuracy = round(correct_count * 100 / total_count)
        return ScoreSummary(
            correct_count=correct_count,
            total_count=total_count,
            accuracy=accuracy,
            earned_xp=correct_count * 20,
            mastered_points=list(dict.fromkeys(mastered)),
            weak_points=list(dict.fromkeys(weak)),
            answer_records=evaluated,
        )

