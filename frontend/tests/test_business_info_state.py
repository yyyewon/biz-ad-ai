from types import SimpleNamespace

from core import auth


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def _fake_streamlit(*, saved_name="DB 가게", saved_location="DB 위치"):
    session_state = SessionState(
        auth={
            "is_logged_in": True,
            "user": {
                "id": 10,
                "store_name": saved_name,
                "store_location": saved_location,
            },
        },
        business={
            "store_name": "URL의 예전 가게",
            "menu_name": "",
            "store_location": "URL의 예전 위치",
            "price": "",
            "purpose": None,
        },
        business_form_epoch=0,
    )
    return SimpleNamespace(session_state=session_state)


def test_saved_business_info_wins_over_stale_session_on_step_one_entry(monkeypatch):
    fake_st = _fake_streamlit()
    monkeypatch.setattr(auth, "st", fake_st)

    auth.apply_saved_business_info(force=True)

    assert fake_st.session_state.business["store_name"] == "DB 가게"
    assert fake_st.session_state.business["store_location"] == "DB 위치"
    assert fake_st.session_state.business_form_epoch == 1


def test_saved_business_info_does_not_overwrite_input_during_same_form(monkeypatch):
    fake_st = _fake_streamlit()
    monkeypatch.setattr(auth, "st", fake_st)

    auth.apply_saved_business_info(force=True)
    fake_st.session_state.business["store_name"] = "입력 중인 가게"
    fake_st.session_state.business["store_location"] = "입력 중인 위치"

    auth.apply_saved_business_info()

    assert fake_st.session_state.business["store_name"] == "입력 중인 가게"
    assert fake_st.session_state.business["store_location"] == "입력 중인 위치"
