from datetime import date, datetime, timedelta


REVIEW_INTERVAL_DAYS = (1, 3, 7, 14, 30)


def xp_for_answer(attempt_type: str, correct: bool, reward_allowed: bool = True) -> int:
    if not correct or not reward_allowed:
        return 0
    return {"normal": 2, "replay": 5, "review": 10}.get(attempt_type, 0)


def update_streak(last_date: date | None, current_days: int, today: date) -> tuple[int, date]:
    if last_date == today:
        return current_days, today
    if last_date == today - timedelta(days=1):
        return current_days + 1, today
    return 1, today


def next_review_state(current_stage: int, correct: bool, now: datetime) -> tuple[int, str, datetime | None]:
    if not correct:
        return 0, "active", now + timedelta(days=REVIEW_INTERVAL_DAYS[0])
    next_stage = min(current_stage + 1, len(REVIEW_INTERVAL_DAYS))
    if next_stage >= len(REVIEW_INTERVAL_DAYS):
        return next_stage, "mastered", None
    return next_stage, "active", now + timedelta(days=REVIEW_INTERVAL_DAYS[next_stage])


def calculate_mastery(recent_results: list[bool], review_stage: int, has_review: bool) -> int:
    accuracy = sum(recent_results[-5:]) / max(1, len(recent_results[-5:]))
    if not has_review:
        return round(accuracy * 100)
    review_progress = min(1.0, review_stage / 5)
    return round(accuracy * 70 + review_progress * 30)
