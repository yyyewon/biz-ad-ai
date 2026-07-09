"""
소셜 로그인 상태 관리 모듈
"""
from __future__ import annotations

import requests
import streamlit as st

from core.config import DEV_GUEST_MODE_DEFAULT, ME_ENDPOINT, DEV_RESET_QUOTA_ENDPOINT, REQUEST_TIMEOUT_AUTH


def init_auth_state() -> None:
    if "auth" not in st.session_state:
        st.session_state.auth = {"is_logged_in": False, "user": None}
    
    if "is_logged_in" not in st.session_state.auth:
        st.session_state.auth["is_logged_in"] = False


def is_logged_in(session_state: dict | None = None) -> bool:
    if session_state is None:
        session_state = st.session_state
    return bool(session_state.get("auth", {}).get("access_token"))


def is_dev_guest_mode(session_state: dict | None = None) -> bool:
    """로그인 우회 모드. 실제 로그인 상태면 항상 False."""
    if session_state is None:
        session_state = st.session_state
    if is_logged_in(session_state=session_state):
        return False
    return bool(session_state.get("dev_guest_mode", DEV_GUEST_MODE_DEFAULT))


def should_allow_access(mock_mode: bool | None = None, dev_guest_mode: bool | None = None, session_state: dict | None = None) -> bool:
    if session_state is None:
        session_state = st.session_state
    if mock_mode is None:
        mock_mode = session_state.get("mock_mode", False)
    if dev_guest_mode is None:
        dev_guest_mode = is_dev_guest_mode(session_state=session_state)
    return bool(mock_mode or is_logged_in(session_state=session_state) or dev_guest_mode)


# ✨ HEAD 브랜치의 쿠키 기반 인증 상태 체크 함수 유지
def check_auth_status_from_cookies(cookies: dict) -> None:
    """
    브라우저 쿠키에 담긴 토큰을 기반으로 최초 로그인 세션 수립
    """
    init_auth_state()
    
    if st.session_state.auth["is_logged_in"]:
        return
    

    try:
        res = requests.get(
            ME_ENDPOINT,
            cookies=cookies,
            timeout=REQUEST_TIMEOUT_AUTH,
        )
        if res.status_code == 200:
            st.session_state.auth = {"is_logged_in": True, "user": res.json().get("data")}
            # 로그인 성공 시 우회 모드는 자동 해제
            st.session_state.dev_guest_mode = False
    except requests.exceptions.RequestException:
        pass


def refresh_me(cookies: dict) -> None:
    """
    로그인된 상태에서 오늘 생성 사용량 등 최신 정보를 다시 가져오기
    """
    try:
        res = requests.get(
            ME_ENDPOINT,
            cookies=cookies,
            timeout=REQUEST_TIMEOUT_AUTH,
        )
        if res.status_code == 200:
            st.session_state.auth["user"] = res.json().get("data")
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


# ===============================================================
# ✨ [컴포넌트 연동용 블록] 삭제되었던 필수 메서드 완벽 부활 및 쿠키 연동
# ===============================================================

def get_daily_usage() -> dict | None:
    """
    세션에 저장된 사용자 정보에서 오늘 생성 사용량 반환
    """
    user = st.session_state.auth.get("user")
    if not user:
        return None
    return user.get("daily_usage")


def is_quota_exceeded() -> bool:
    """
    오늘 생성 가능 횟수를 모두 사용했는지 확인
    """
    if st.session_state.get("mock_mode"):
        return False
    usage = get_daily_usage()
    if not usage:
        return False
    return usage.get("remaining", 1) <= 0


def sync_usage(cookies: dict) -> None:
    """
    로그인 상태에서 최신 사용량 정보를 서버에서 다시 가져와 세션에 반영
    """
    if st.session_state.get("mock_mode") or not is_logged_in():
        return
    refresh_me(cookies)


def reset_quota_for_testing(cookies: dict) -> tuple[bool, str]:
    """
    테스트용: 오늘 생성 횟수 초기화
    """
    if not is_logged_in():
        return False, "로그인 후 이용할 수 있어요."

    try:
        res = requests.post(
            DEV_RESET_QUOTA_ENDPOINT,
            cookies=cookies,
            timeout=REQUEST_TIMEOUT_AUTH,
        )
    except requests.exceptions.RequestException:
        return False, "서버에 연결할 수 없어요."

    if res.status_code == 200:
        refresh_me(cookies)
        return True, "오늘 생성 횟수를 초기화했어요."

    try:
        message = res.json().get("error", {}).get("message", "초기화에 실패했어요.")
    except ValueError:
        message = "초기화에 실패했어요."
    return False, message