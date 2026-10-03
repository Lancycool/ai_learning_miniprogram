from datetime import date, datetime, timedelta

import pytest

from app.core.security import TokenService
from app.services.learning_rules import (
    calculate_mastery,
    next_review_state,
    update_streak,
    xp_for_answer,
)


def test_access_token_contains_only_required_identity_fields() -> None:
    service = TokenService("secret-for-tests", "issuer", "audience", 15, 30)
    token = service.create_access_token("usr_123", "ses_456")
    payload = service.decode_access_token(token)
    assert payload["sub"] == "usr_123"
    assert payload["sid"] == "ses_456"
    assert payload["type"] == "access"
    assert "openid" not in payload
    assert "nickname" not in payload


def test_refresh_tokens_are_random_and_hashed() -> None:
    service = TokenService("secret-for-tests", "issuer", "audience", 15, 30)
    first = service.create_refresh_token()
    second = service.create_refresh_token()
    assert first != second
    assert service.hash_refresh_token(first) != first
    assert len(service.hash_refresh_token(first)) == 64


@pytest.mark.parametrize(
    ("attempt_type", "correct", "rewarded", "expected"),
    [("normal", True, True, 2), ("normal", False, True, 0), ("replay", True, True, 5), ("replay", True, False, 0), ("review", True, True, 10)],
)
def test_xp_rules(attempt_type: str, correct: bool, rewarded: bool, expected: int) -> None:
    assert xp_for_answer(attempt_type, correct, rewarded) == expected


def test_streak_uses_china_calendar_days() -> None:
    today = date(2026, 9, 27)
    assert update_streak(None, 0, today) == (1, today)
    assert update_streak(today, 7, today) == (7, today)
    assert update_streak(today - timedelta(days=1), 7, today) == (8, today)
    assert update_streak(today - timedelta(days=2), 7, today) == (1, today)


def test_review_fifth_success_marks_mastered() -> None:
    now = datetime(2026, 9, 27, 4, 0)
    stage, status, next_at = next_review_state(4, True, now)
    assert (stage, status, next_at) == (5, "mastered", None)


def test_review_failure_resets_to_first_interval() -> None:
    now = datetime(2026, 9, 27, 4, 0)
    stage, status, next_at = next_review_state(3, False, now)
    assert stage == 0
    assert status == "active"
    assert next_at == now + timedelta(days=1)


def test_mastery_uses_accuracy_and_review_progress() -> None:
    assert calculate_mastery([True, True, True, False, False], 3, True) == 60
    assert calculate_mastery([True, False], 0, False) == 50
