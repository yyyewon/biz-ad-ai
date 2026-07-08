"""
소셜 로그인 상태 관리 모듈
"""
from __future__ import annotations

import requests
import streamlit as st

from core.config import ME_ENDPOINT, DEV_RESET_QUOTA_ENDPOINT, REQUEST_TIMEOUT_AUTH, DEV_GUEST_MODE_DEFAULT


def init_auth_state() -> None:
    if "auth" not in st.session_state:
        st.session_state.auth = {"access_token": None, "user": None}


def is_logged_in() -> bool:
    return bool(st.session_state.auth.get("access_token"))


def is_dev_guest_mode() -> bool:
    """로그인 우회 모드. 실제 로그인 상태면 항상 False."""
    if is_logged_in():
        return False
    return bool(st.session_state.get("dev_guest_mode", DEV_GUEST_MODE_DEFAULT))


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
    세션에 토큰 저장 후 주소창에서 제거
    """
    init_auth_state()

    token = st.query_params.get("login_token")
    if not token:
        return

    user = fetch_me(token)
    if user is None:
        st.session_state.auth = {"access_token": None, "user": None}
    else:
        st.session_state.auth = {"access_token": token, "user": user}
        # 로그인 성공 시 우회 모드는 자동 해제
        st.session_state.dev_guest_mode = False

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
    st.session_state.auth = {"access_token": None, "user": None}



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