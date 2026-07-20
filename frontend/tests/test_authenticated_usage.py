from types import SimpleNamespace

from core import auth


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _fake_streamlit(*, logged_in: bool, mock_mode: bool, remaining: int = 0):
    user = None
    if logged_in:
        user = {
            "daily_usage": {
                "used": 3 - remaining,
                "limit": 3,
                "remaining": remaining,
            }
        }

    return SimpleNamespace(
        session_state=SessionState(
            auth={"is_logged_in": logged_in, "user": user},
            mock_mode=mock_mode,
        )
    )


def test_quota_is_applied_to_logged_in_user(monkeypatch):
    monkeypatch.setattr(
        auth,
        "st",
        _fake_streamlit(logged_in=True, mock_mode=False, remaining=0),
    )

    assert auth.is_quota_exceeded() is True


def test_quota_is_not_applied_to_anonymous_or_mock_mode(monkeypatch):
    monkeypatch.setattr(
        auth,
        "st",
        _fake_streamlit(logged_in=False, mock_mode=False),
    )
    assert auth.is_quota_exceeded() is False

    monkeypatch.setattr(
        auth,
        "st",
        _fake_streamlit(logged_in=True, mock_mode=True, remaining=0),
    )
    assert auth.is_quota_exceeded() is False
