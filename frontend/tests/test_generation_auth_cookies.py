from types import SimpleNamespace

from components import step_result


def test_capture_generation_cookies_copies_logged_in_context(monkeypatch):
    source_cookies = {"access_token": "access", "refresh_token": "refresh"}
    fake_st = SimpleNamespace(context=SimpleNamespace(cookies=source_cookies))

    monkeypatch.setattr(step_result, "st", fake_st)
    monkeypatch.setattr(step_result, "is_logged_in", lambda: True)

    captured = step_result._capture_generation_cookies(mock=False)

    assert captured == source_cookies
    assert captured is not source_cookies


def test_capture_generation_cookies_skips_mock_and_anonymous(monkeypatch):
    fake_st = SimpleNamespace(
        context=SimpleNamespace(cookies={"access_token": "must-not-be-used"})
    )
    monkeypatch.setattr(step_result, "st", fake_st)

    monkeypatch.setattr(step_result, "is_logged_in", lambda: True)
    assert step_result._capture_generation_cookies(mock=True) is None

    monkeypatch.setattr(step_result, "is_logged_in", lambda: False)
    assert step_result._capture_generation_cookies(mock=False) is None
