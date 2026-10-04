from calendar import monthrange
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, ResourceNotFoundError
from app.db.base import utc_now
from app.db.models import AnswerRecord, AttemptQuestion, KnowledgeDomain, LearningAttempt, LearningReport, MistakeRecord, Question, Quiz, User, UserDailyStat, XpTransaction
from app.services.auth_service import public_id
from app.services.learning_rules import calculate_mastery, next_review_state, update_streak, xp_for_answer
from app.models.web_search import search_view


def question_view(question: Question, reveal: bool = False, reveal_sources: bool = False) -> dict:
    value = {"question_id": question.public_id, "type": question.question_type, "stem": question.stem, "options": question.options_json, "knowledge_point": question.knowledge_point, "difficulty": question.difficulty}
    if reveal:
        value.update({"answer": question.answer_json, "explanation": question.explanation})
    if reveal_sources and question.source_metadata_json:
        value["sources"] = question.source_metadata_json
    return value


class LearningService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_attempt(self, user: User, quiz_public_id: str, attempt_type: str = "normal", *, commit: bool = True) -> dict:
        quiz = await self.db.scalar(select(Quiz).where(Quiz.public_id == quiz_public_id, Quiz.user_id == user.id, Quiz.generation_status == "ready"))
        if not quiz:
            raise ResourceNotFoundError()
        questions = (await self.db.scalars(select(Question).where(Question.quiz_id == quiz.id).order_by(Question.sequence_no))).all()
        if quiz.source_type == "original" and attempt_type == "normal":
            await self.db.scalar(select(User.id).where(User.id == user.id).with_for_update())
            previous = await self.db.scalar(select(LearningAttempt.id).where(LearningAttempt.user_id == user.id,
                LearningAttempt.quiz_id == quiz.id, LearningAttempt.attempt_type == "normal").limit(1).with_for_update())
            if previous:
                attempt_type = "replay"
        attempt = LearningAttempt(public_id=public_id("att"), user_id=user.id, quiz_id=quiz.id, attempt_type=attempt_type, total_count=len(questions))
        self.db.add(attempt)
        await self.db.flush()
        self.db.add_all([AttemptQuestion(attempt_id=attempt.id, question_id=q.id, sequence_no=i) for i, q in enumerate(questions, 1)])
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        return await self.get_attempt(user, attempt.public_id)

    async def get_attempt(self, user: User, attempt_public_id: str) -> dict:
        attempt = await self.db.scalar(select(LearningAttempt).where(LearningAttempt.public_id == attempt_public_id, LearningAttempt.user_id == user.id))
        if not attempt:
            raise ResourceNotFoundError()
        quiz = await self.db.get(Quiz, attempt.quiz_id) if attempt.quiz_id else None
        report = await self.db.scalar(select(LearningReport).where(LearningReport.attempt_id == attempt.id))
        rows = (await self.db.execute(select(Question, AnswerRecord).join(AttemptQuestion, AttemptQuestion.question_id == Question.id).outerjoin(AnswerRecord, and_(AnswerRecord.attempt_id == attempt.id, AnswerRecord.question_id == Question.id)).where(AttemptQuestion.attempt_id == attempt.id).order_by(AttemptQuestion.sequence_no))).all()
        items = []
        for question, answer in rows:
            item = question_view(question, reveal=answer is not None or attempt.status == "completed", reveal_sources=attempt.status == "completed")
            if answer:
                item["result"] = {"selected_answers": answer.selected_answers_json, "is_correct": answer.is_correct, "duration_ms": answer.duration_ms}
            items.append(item)
        report_data = None
        is_private = any(q.source_metadata_json for q, _ in rows)
        if report:
            report_data = {
                "mastered_points": report.mastered_points_json,
                "weak_points": report.weak_points_json,
                "three_line_summary": report.three_line_summary_json,
                "advice": report.advice_json,
                "share_quote": report.share_quote,
                "is_private": is_private,
            }
        return {"attempt_id": attempt.public_id, "title": quiz.title if quiz else "错题复习", "quiz_id": quiz.public_id if quiz else None, "attempt_type": attempt.attempt_type, "status": attempt.status, "current_sequence": attempt.current_sequence, "correct_count": attempt.correct_count, "total_count": attempt.total_count, "accuracy": attempt.accuracy, "earned_xp": attempt.earned_xp, "started_at": attempt.started_at, "completed_at": attempt.completed_at, "report": report_data, "questions": items, "is_private": is_private, "source_type": quiz.source_type if quiz else "review", "web_search": search_view(quiz.web_search_metadata_json, reveal=attempt.status == "completed") if quiz else None}

    async def submit_answer(self, user: User, attempt_public_id: str, question_public_id: str, selected: list[str], duration_ms: int, key: str) -> dict:
        attempt = await self.db.scalar(select(LearningAttempt).where(LearningAttempt.public_id == attempt_public_id, LearningAttempt.user_id == user.id))
        if not attempt:
            raise ResourceNotFoundError()
        if attempt.status != "in_progress":
            raise ConflictError("本次闯关已经结束")
        existing = await self.db.scalar(select(AnswerRecord).where(AnswerRecord.attempt_id == attempt.id, AnswerRecord.idempotency_key == key))
        if existing:
            question = await self.db.get(Question, existing.question_id)
            return self._answer_payload(attempt, question, existing, 0)
        question = await self.db.scalar(select(Question).join(AttemptQuestion, AttemptQuestion.question_id == Question.id).where(AttemptQuestion.attempt_id == attempt.id, Question.public_id == question_public_id))
        if not question:
            raise ResourceNotFoundError()
        already = await self.db.scalar(select(AnswerRecord).where(AnswerRecord.attempt_id == attempt.id, AnswerRecord.question_id == question.id))
        if already:
            raise ConflictError("这道题已经提交")
        valid = {item["key"] for item in question.options_json}
        normalized = sorted(set(item.upper() for item in selected))
        if not normalized or not set(normalized).issubset(valid):
            raise ForbiddenError("答案选项无效")
        correct = normalized == sorted(question.answer_json)
        reward_allowed = await self._reward_allowed(attempt)
        xp = xp_for_answer(attempt.attempt_type, correct, reward_allowed)
        answer = AnswerRecord(public_id=public_id("ans"), attempt_id=attempt.id, question_id=question.id, selected_answers_json=normalized, is_correct=correct, duration_ms=duration_ms, idempotency_key=key)
        self.db.add(answer)
        attempt.current_sequence += 1
        attempt.correct_count += int(correct)
        attempt.total_duration_ms += duration_ms
        attempt.earned_xp += xp
        await self._update_mistake(user.id, question.id, attempt.attempt_type, correct)
        await self.db.commit()
        return self._answer_payload(attempt, question, answer, xp)

    async def complete(self, user: User, attempt_public_id: str) -> dict:
        attempt = await self.db.scalar(select(LearningAttempt).where(LearningAttempt.public_id == attempt_public_id, LearningAttempt.user_id == user.id))
        if not attempt:
            raise ResourceNotFoundError()
        if attempt.status == "completed":
            return self._completion_payload(attempt, user)
        answered = await self.db.scalar(select(func.count()).select_from(AnswerRecord).where(AnswerRecord.attempt_id == attempt.id))
        if answered != attempt.total_count:
            raise ConflictError("请完成全部题目后再通关")
        attempt.status = "completed"
        attempt.completed_at = utc_now()
        attempt.accuracy = round(attempt.correct_count * 100 / max(1, attempt.total_count))
        if attempt.attempt_type == "normal":
            attempt.earned_xp += 10
        if attempt.earned_xp:
            reason = f"{attempt.attempt_type}_complete"
            exists = await self.db.scalar(select(XpTransaction).where(XpTransaction.user_id == user.id, XpTransaction.reason_type == reason, XpTransaction.business_id == attempt.public_id))
            if not exists:
                self.db.add(XpTransaction(user_id=user.id, amount=attempt.earned_xp, reason_type=reason, business_id=attempt.public_id))
                user.xp_total += attempt.earned_xp
        china_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        user.current_streak_days, user.last_learning_date = update_streak(user.last_learning_date, user.current_streak_days, china_today)
        user.longest_streak_days = max(user.longest_streak_days, user.current_streak_days)
        stat = await self.db.get(UserDailyStat, (user.id, china_today))
        if not stat:
            stat = UserDailyStat(user_id=user.id, stat_date=china_today, completed_attempts=0, answered_questions=0, correct_answers=0, learning_duration_ms=0, earned_xp=0)
            self.db.add(stat)
        stat.completed_attempts += 1
        stat.answered_questions += attempt.total_count
        stat.correct_answers += attempt.correct_count
        stat.learning_duration_ms += attempt.total_duration_ms
        stat.earned_xp += attempt.earned_xp
        if attempt.attempt_type == "review" and attempt.total_count == 5:
            bonus_key = f"review_bonus:{attempt.public_id}"
            self.db.add(XpTransaction(user_id=user.id, amount=10, reason_type="review_bonus", business_id=bonus_key))
            attempt.earned_xp += 10
            user.xp_total += 10
            stat.earned_xp += 10
        await self.db.commit()
        return self._completion_payload(attempt, user)

    async def history(self, user: User, status: str | None = None, keyword: str | None = None, limit: int = 20) -> list[dict]:
        query = select(LearningAttempt, Quiz).join(Quiz, LearningAttempt.quiz_id == Quiz.id, isouter=True).where(LearningAttempt.user_id == user.id)
        if status:
            query = query.where(LearningAttempt.status == status)
        if keyword:
            query = query.where(Quiz.title.like(f"%{keyword}%"))
        rows = (await self.db.execute(query.order_by(LearningAttempt.started_at.desc(), LearningAttempt.id.desc()).limit(min(limit, 50)))).all()
        return [{"attempt_id": a.public_id, "title": q.title if q else "错题复习", "status": a.status, "correct_count": a.correct_count, "total_count": a.total_count, "accuracy": a.accuracy, "earned_xp": a.earned_xp, "duration_ms": a.total_duration_ms, "started_at": a.started_at, "completed_at": a.completed_at} for a, q in rows]

    async def overview(self, user: User) -> dict:
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        start = today - timedelta(days=today.weekday())
        stats = (await self.db.scalars(select(UserDailyStat).where(UserDailyStat.user_id == user.id, UserDailyStat.stat_date >= start, UserDailyStat.stat_date <= today))).all()
        recent = await self.db.scalar(select(LearningAttempt).where(LearningAttempt.user_id == user.id, LearningAttempt.status == "in_progress").order_by(LearningAttempt.started_at.desc()))
        totals = (await self.db.execute(
            select(
                func.coalesce(func.sum(UserDailyStat.completed_attempts), 0),
                func.coalesce(func.sum(UserDailyStat.answered_questions), 0),
                func.coalesce(func.sum(UserDailyStat.correct_answers), 0),
            ).where(UserDailyStat.user_id == user.id)
        )).one()
        total_completed, total_answered, total_correct = (int(value or 0) for value in totals)
        weekly = {item.stat_date.isoformat(): {"completed": item.completed_attempts, "xp": item.earned_xp} for item in stats}
        return {
            "user": {"nickname": user.nickname, "avatar_url": user.avatar_url, "xp_total": user.xp_total, "current_streak_days": user.current_streak_days},
            "total_completed": total_completed,
            "total_answered": total_answered,
            "total_correct": total_correct,
            "average_accuracy": round(total_correct * 100 / total_answered) if total_answered else 0,
            "week_completed": sum(x.completed_attempts for x in stats),
            "week_xp": sum(x.earned_xp for x in stats),
            "recent_attempt_id": recent.public_id if recent else None,
            "recent_remaining": recent.total_count - recent.current_sequence + 1 if recent else 0,
            "recent_history": await self.history(user, status="completed", limit=5),
            "week_days": weekly,
        }

    async def mistakes(self, user: User) -> dict:
        rows = (await self.db.execute(select(MistakeRecord, Question, Quiz).join(Question, MistakeRecord.question_id == Question.id).join(Quiz, Question.quiz_id == Quiz.id).where(MistakeRecord.user_id == user.id).order_by(MistakeRecord.next_review_at))).all()
        now = utc_now()
        items = [{"question_id": q.public_id, "topic": quiz.title, "stem": q.stem, "wrong_count": m.wrong_count, "review_stage": m.review_stage, "status": m.status, "next_review_at": m.next_review_at} for m, q, quiz in rows]
        return {"total": sum(x[0].status == "active" for x in rows), "due": sum(x[0].status == "active" and x[0].next_review_at and x[0].next_review_at <= now for x in rows), "items": items}

    async def create_review(self, user: User) -> dict:
        now = utc_now()
        rows = (await self.db.execute(select(MistakeRecord, Question).join(Question, MistakeRecord.question_id == Question.id).where(MistakeRecord.user_id == user.id, MistakeRecord.status == "active", MistakeRecord.next_review_at <= now).order_by(MistakeRecord.next_review_at).limit(5))).all()
        if not rows:
            raise ResourceNotFoundError("目前没有到期错题")
        attempt = LearningAttempt(public_id=public_id("att"), user_id=user.id, attempt_type="review", total_count=len(rows))
        self.db.add(attempt)
        await self.db.flush()
        self.db.add_all([AttemptQuestion(attempt_id=attempt.id, question_id=q.id, sequence_no=i) for i, (_, q) in enumerate(rows, 1)])
        await self.db.commit()
        return await self.get_attempt(user, attempt.public_id)

    async def monthly(self, user: User, month: str) -> dict:
        year, month_no = map(int, month.split("-"))
        start = date(year, month_no, 1)
        end = date(year, month_no, monthrange(year, month_no)[1])
        stats = (await self.db.scalars(select(UserDailyStat).where(UserDailyStat.user_id == user.id, UserDailyStat.stat_date.between(start, end)))).all()
        completed = sum(x.completed_attempts for x in stats)
        answered = sum(x.answered_questions for x in stats)
        correct = sum(x.correct_answers for x in stats)
        return {"month": month, "completed_attempts": completed, "average_accuracy": round(correct * 100 / answered) if answered else 0, "learning_duration_ms": sum(x.learning_duration_ms for x in stats), "earned_xp": sum(x.earned_xp for x in stats), "advice": "保持稳定学习节奏，并优先复习已经到期的错题。" if completed else "完成第一次闯关后，团团会在这里整理学习建议。"}

    async def garden(self, user: User) -> list[dict]:
        domains = (await self.db.scalars(select(KnowledgeDomain).order_by(KnowledgeDomain.sort_order))).all()
        result = []
        for domain in domains:
            questions = (await self.db.scalars(select(Question).join(Quiz, Question.quiz_id == Quiz.id).where(Quiz.user_id == user.id, Quiz.domain_id == domain.id))).all()
            mastery_values = []
            for q in questions:
                answers = (await self.db.scalars(select(AnswerRecord).join(LearningAttempt, AnswerRecord.attempt_id == LearningAttempt.id).where(LearningAttempt.user_id == user.id, AnswerRecord.question_id == q.id).order_by(AnswerRecord.answered_at.desc()).limit(5))).all()
                mistake = await self.db.scalar(select(MistakeRecord).where(MistakeRecord.user_id == user.id, MistakeRecord.question_id == q.id))
                mastery_values.append(calculate_mastery([a.is_correct for a in reversed(answers)], mistake.review_stage if mistake else 0, mistake is not None))
            mastery = round(sum(mastery_values) / len(mastery_values)) if mastery_values else 0
            result.append({"code": domain.code, "name": domain.name, "knowledge_count": len(questions), "mastery": mastery, "status": "mastered" if mastery >= 80 else "unlocked" if mastery >= 60 or questions else "locked"})
        return result

    async def _reward_allowed(self, attempt: LearningAttempt) -> bool:
        if attempt.attempt_type == "normal" or attempt.attempt_type == "review":
            return True
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        start = datetime.combine(today, datetime.min.time()) - timedelta(hours=8)
        return not bool(await self.db.scalar(select(LearningAttempt.id).where(LearningAttempt.user_id == attempt.user_id, LearningAttempt.quiz_id == attempt.quiz_id, LearningAttempt.attempt_type == "replay", LearningAttempt.status == "completed", LearningAttempt.completed_at >= start)))

    async def _update_mistake(self, user_id: int, question_id: int, attempt_type: str, correct: bool) -> None:
        item = await self.db.scalar(select(MistakeRecord).where(MistakeRecord.user_id == user_id, MistakeRecord.question_id == question_id))
        now = utc_now()
        if not correct:
            if not item:
                item = MistakeRecord(user_id=user_id, question_id=question_id, next_review_at=now + timedelta(days=1))
                self.db.add(item)
            else:
                item.wrong_count += 1
                item.last_wrong_at = now
                if attempt_type == "review":
                    item.review_stage, item.status, item.next_review_at = next_review_state(item.review_stage, False, now)
            return
        if attempt_type == "review" and item:
            item.review_stage, item.status, item.next_review_at = next_review_state(item.review_stage, True, now)
            item.review_success_count += 1
            item.last_reviewed_at = now
            item.mastered_at = now if item.status == "mastered" else None

    @staticmethod
    def _answer_payload(attempt: LearningAttempt, question: Question, answer: AnswerRecord, xp: int) -> dict:
        return {"is_correct": answer.is_correct, "correct_answers": question.answer_json, "explanation": question.explanation, "knowledge_point": question.knowledge_point, "earned_xp_delta": xp, "progress": {"answered": attempt.current_sequence - 1, "total": attempt.total_count}}

    @staticmethod
    def _completion_payload(attempt: LearningAttempt, user: User) -> dict:
        return {"attempt_id": attempt.public_id, "status": attempt.status, "correct_count": attempt.correct_count, "total_count": attempt.total_count, "accuracy": attempt.accuracy, "earned_xp": attempt.earned_xp, "xp_total": user.xp_total, "current_streak_days": user.current_streak_days}
