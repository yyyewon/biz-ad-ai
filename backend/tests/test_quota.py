import pytest

from app.core import database
from app.core import quota
from app.core.exceptions import AppException
from app.core.user_repository import get_or_create_user


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test_app.db")
    database.init_db()


def _make_user(provider_user_id: str) -> int:
    user = get_or_create_user(
        provider="google",
        provider_user_id=provider_user_id,
        email=None,
        nickname=None,
    )
    return user["id"]


def test_daily_usage_increments_and_blocks_after_limit():
    user_id = _make_user("user-1")

    for expected in range(1, quota.DAILY_LIMIT + 1):
        count = quota.check_and_increment_daily_usage(user_id)
        assert count == expected

    with pytest.raises(AppException) as exc_info:
        quota.check_and_increment_daily_usage(user_id)

    assert exc_info.value.code == "DAILY_LIMIT_EXCEEDED"
    assert exc_info.value.status_code == 429


def test_get_daily_usage_reports_remaining():
    user_id = _make_user("user-2")

    quota.check_and_increment_daily_usage(user_id)
    usage = quota.get_daily_usage(user_id)

    assert usage["used"] == 1
    assert usage["limit"] == quota.DAILY_LIMIT
    assert usage["remaining"] == quota.DAILY_LIMIT - 1


def test_usage_is_isolated_per_user():
    user_id_a = _make_user("user-a")
    user_id_b = _make_user("user-b")

    quota.check_and_increment_daily_usage(user_id_a)
    quota.check_and_increment_daily_usage(user_id_a)

    usage_a = quota.get_daily_usage(user_id_a)
    usage_b = quota.get_daily_usage(user_id_b)

    assert usage_a["used"] == 2
    assert usage_b["used"] == 0
