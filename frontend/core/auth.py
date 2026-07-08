"""
소셜 로그인 상태 관리 모듈
"""
from __future__ import annotations

import requests
import streamlit as st

from core.config import ME_ENDPOINT, REQUEST_TIMEOUT_AUTH


def init_auth_state() -> None:
    if "auth" not in st.session_state:
        st.session_state.auth = {"is_logged_in": False, "user": None}


def is_logged_in() -> bool:
    return st.session_state.auth.get("is_logged_in", False)


def check_auth_status_from_cookies(cookies: dict) -> None:
    """
    브라우저 쿠키에 담긴 토큰을 기반으로 최초 로그인 세션 수립
    """
    init_auth_state()
    if st.session_state.auth["is_logged_in"]:
        return

    # 쿠키 전송을 위해 requests Session 객체나 쿠키 헤더 활용
    try:
        res = requests.get(
            ME_ENDPOINT,
            cookies=cookies,
            timeout=REQUEST_TIMEOUT_AUTH,
        )
        if res.status_code == 200:
            st.session_state.auth = {"is_logged_in": True, "user": res.json().get("data")}
    except requests.exceptions.RequestException:
        pass


def request_refresh_token(cookies: dict) -> bool:
    """
    401 발생 시 쿠키를 실어 서버에 토큰 재발급을 요청합니다.
    """
    try:
        refresh_endpoint = ME_ENDPOINT.replace("/me", "/refresh")
        res = requests.post(
            refresh_endpoint,
            cookies=cookies,
            timeout=REQUEST_TIMEOUT_AUTH
        )
        if res.status_code == 200:
            return True
    except Exception:
        pass
        
    logout_session()
    return False


def logout_session() -> None:
    st.session_state.auth = {"is_logged_in": False, "user": None}
    st.query_params.clear()