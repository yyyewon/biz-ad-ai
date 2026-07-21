from types import SimpleNamespace

from components import step_result
from core import state


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def test_failed_attempt_with_same_signature_does_not_start_automatically():
    signature = ("store", "menu", "input")
    generation = {
        "status": "error",
        "signature": signature,
        "error_code": "OPENAI_AUTHENTICATION_FAILED",
    }

    assert step_result._should_start_generation(generation, signature) is False


def test_generation_starts_only_for_explicit_retry_or_changed_input():
    old_signature = ("store", "menu", "old")
    new_signature = ("store", "menu", "new")

    assert step_result._should_start_generation(
        {"status": "idle", "signature": old_signature},
        old_signature,
    ) is True
    assert step_result._should_start_generation(
        {"status": "error", "signature": old_signature},
        new_signature,
    ) is True
    assert step_result._should_start_generation(
        {"status": "loading", "signature": old_signature},
        new_signature,
    ) is False


def test_generation_loading_records_attempt_signature(monkeypatch):
    fake_st = SimpleNamespace(
        session_state=SessionState(
            generation={
                "status": "error",
                "error_message": "previous error",
                "error_code": "PREVIOUS_ERROR",
                "signature": None,
            }
        )
    )
    monkeypatch.setattr(state, "st", fake_st)

    signature = ("store", "menu", "attempt")
    state.set_generation_loading(signature)

    assert fake_st.session_state.generation == {
        "status": "loading",
        "error_message": "",
        "error_code": None,
        "signature": signature,
    }
