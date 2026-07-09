"""
소셜 로그인 상태 관리 모듈
"""
from __future__ import annotations

import requests
import streamlit as st

from core.config import DEV_GUEST_MODE_DEFAULT, ME_ENDPOINT, DEV_RESET_QUOTA_ENDPOINT, REQUEST_TIMEOUT_AUTH


def init_auth_state() -> None:
    if "auth" not in st.session_state:
        st.session_state.auth = {"access_token": None, "refresh_token": None, "user": None}


def is_logged_in(session_state: dict | None = None) -> bool:
    if session_state is None:
        session_state = st.session_state
    return bool(session_state.get("auth", {}).get("access_token"))


def should_allow_access(mock_mode: bool | None = None, dev_guest_mode: bool | None = None, session_state: dict | None = None) -> bool:
    if session_state is None:
        session_state = st.session_state
    if mock_mode is None:
        mock_mode = session_state.get("mock_mode", False)
    if dev_guest_mode is None:
        dev_guest_mode = session_state.get("dev_guest_mode", DEV_GUEST_MODE_DEFAULT)
    return bool(mock_mode or is_logged_in(session_state=session_state) or dev_guest_mode)


def fetch_me(access_token: str) -> dict | None:
    """
    /api/v1/auth/me 호출로 사용자 정보 + 오늘 생성 사용량 요청
    """
    try:
        res = requests.get(
            ME_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT_AUTH,
        )
        if res.status_code != 200:
            return None
        body = res.json()
        return body.get("data")
    except requests.exceptions.RequestException:
        return None


def consume_login_token_from_query() -> None:
    """
    세션에 Access & Refresh 토큰 저장 후 주소창에서 제거
    """
    init_auth_state()

    # 💡 백엔드에서 리다이렉트해 준 두 토큰을 모두 낚아챕니다.
    access_token = st.query_params.get("login_token")
    refresh_token = st.query_params.get("refresh_token")
    
    if not access_token:
        return

    user = fetch_me(access_token)
    if user is None:
        st.session_state.auth = {"access_token": None, "refresh_token": None, "user": None}
    else:
        # 💡 세션에 Refresh Token도 안전하게 박아둡니다.
        st.session_state.auth = {
            "access_token": access_token, 
            "refresh_token": refresh_token, 
            "user": user
        }

    st.query_params.clear()
    st.rerun()


def refresh_me() -> None:
    """
    로그인된 상태에서 오늘 생성 사용량 등 최신 정보를 다시 가져오기
    """
    token = st.session_state.auth.get("access_token")
    if not token:
        return
    user = fetch_me(token)
    if user is not None:
        st.session_state.auth["user"] = user


def logout() -> None:
    st.session_state.auth = {"access_token": None, "refresh_token": None, "user": None}


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


def sync_usage() -> None:
    """
    로그인 상태에서 최신 사용량 정보를 서버에서 다시 가져와 세션에 반영
    """
    if st.session_state.get("mock_mode") or not is_logged_in():
        return
    refresh_me()


def reset_quota_for_testing() -> tuple[bool, str]:
    """
    테스트용: 오늘 생성 횟수 초기화
    """
    token = st.session_state.auth.get("access_token")
    if not token:
        return False, "로그인 후 이용할 수 있어요."

    try:
        res = requests.post(
            DEV_RESET_QUOTA_ENDPOINT,
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT_AUTH,
        )
    except requests.exceptions.RequestException:
        return False, "서버에 연결할 수 없어요."

    if res.status_code == 200:
        refresh_me()
        return True, "오늘 생성 횟수를 초기화했어요."

    try:
        message = res.json().get("error", {}).get("message", "초기화에 실패했어요.")
    except ValueError:
        message = "초기화에 실패했어요."
    return False, message


def request_refresh_token() -> bool:
    """
    💡 401 발생 시 백엔드에 토큰 갱신을 요청하는 구원 함수
    """
    refresh_token = st.session_state.auth.get("refresh_token")
    if not refresh_token:
        return False

    try:
        # ME_ENDPOINT(/api/v1/auth/me) 주소를 기반으로 /api/v1/auth/refresh 주소를 동적으로 유추합니다.
        refresh_endpoint = ME_ENDPOINT.replace("/me", "/refresh")
        res = requests.post(
            refresh_endpoint,
            json={"refresh_token": refresh_token},
            timeout=REQUEST_TIMEOUT_AUTH
        )
        if res.status_code == 200:
            res_data = res.json().get("data", {})
            st.session_state.auth["access_token"] = res_data.get("access_token")
            st.session_state.auth["refresh_token"] = res_data.get("refresh_token")
            return True
    except Exception:
        pass
        
    # Refresh 토큰마저 만료되었으면 세션을 파괴하고 아웃시킵니다.
    logout()
    return False