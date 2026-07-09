"""
소상공인 두레 - 소상공인을 위한 AI 광고 콘텐츠 생성 서비스
"""
from __future__ import annotations
from pathlib import Path
import streamlit as st

from core.state import init_state
from core.api_client import check_backend_health
from core.auth import (
    init_auth_state,
    check_auth_status_from_cookies,
    is_logged_in,
    is_dev_guest_mode,
    logout_session,  
    sync_usage,
    reset_quota_for_testing,
)
from components.layout import render_topbar, render_stepper, render_footer
from components import step_business_info, step_upload, step_result, step_login

st.set_page_config(
    page_title="소상공인 두레 | AI 광고 콘텐츠 생성",
    page_icon="📸",
    layout="wide",
    initial_sidebar_state="expanded",
)


_CSS_PATH = Path(__file__).parent / "assets" / "style.css"


@st.cache_resource(show_spinner=False)
def _load_css(_mtime: float) -> str:
    return _CSS_PATH.read_text(encoding="utf-8")


def _inject_css() -> None:
    st.markdown(f"<style>{_load_css(_CSS_PATH.stat().st_mtime)}</style>", unsafe_allow_html=True)


def _render_login_section() -> None:
    st.markdown("### 👤 로그인")

    if is_logged_in():
        user = st.session_state.auth.get("user") or {}
        nickname = user.get("nickname") or "사용자"
        usage = user.get("daily_usage") or {}
        used = usage.get("used", 0)
        limit = usage.get("limit", 3)

        st.success(f"{nickname}님 환영해요 👋")
        st.caption(f"오늘 생성 {used}/{limit}회 사용")
        if st.button("로그아웃", width="stretch"):
            logout_session()
            st.rerun()
    else:
        st.caption("메인 화면에서 카카오 로그인 후 이용할 수 있어요.")
        if st.session_state.mock_mode:
            st.caption("지금은 목업 모드라 로그인 없이 체험 중이에요.")


def _render_dev_tools() -> None:
    if st.session_state.mock_mode or not is_logged_in():
        return

    st.divider()
    st.markdown("### 🧪 테스트 도구")
    st.caption("백엔드 DEV_TOOLS_ENABLED=true 일 때만 동작해요. (배포 환경에서는 비활성화 권장)")
    if st.button("오늘 생성 횟수 초기화", width="stretch"):
        ok, message = reset_quota_for_testing(st.context.cookies)
        if ok:
            st.success(message)
        else:
            st.error(message)


def _render_sidebar() -> None:
    with st.sidebar:
        _render_login_section()
        _render_dev_tools()
        st.divider()

        st.markdown("### ⚙️ 개발 / 데모 설정")
        st.caption("백엔드(A·C·D 담당)가 준비되기 전까지는 목업 모드로 프론트 작업을 이어갈 수 있어요.")

        st.session_state.mock_mode = st.toggle(
            "목업 모드 (백엔드 없이 테스트)",
            value=st.session_state.mock_mode,
        )
        if is_logged_in():
            st.session_state.dev_guest_mode = False

        st.session_state.dev_guest_mode = st.toggle(
            "로그인 우회 모드 (개발용)",
            value=st.session_state.dev_guest_mode,
            help="카카오 로그인 없이 Step 1/2/3 테스트를 진행합니다.",
            disabled=is_logged_in(),
        )
        if is_logged_in():
            st.caption("로그인된 상태에서는 우회 모드가 적용되지 않아요.")

        if not st.session_state.mock_mode:
            if st.button("서버 연결 상태 확인", width="stretch"):
                with st.spinner("연결 확인 중..."):
                    ok = check_backend_health()
                if ok:
                    st.success("백엔드 서버와 정상적으로 연결됐어요.")
                else:
                    st.error("백엔드 서버에 연결할 수 없어요. API_BASE_URL 설정을 확인해 주세요.")

        st.divider()
        st.caption("Step {}/3 진행 중".format(st.session_state.step))
        if st.button(
            "처음부터 다시 시작",
            width="stretch",
            disabled=(st.session_state.step == 1),
        ):
            from core.state import reset_all
            reset_all()
            st.rerun()


def main() -> None:
    init_state()
    init_auth_state()
    check_auth_status_from_cookies(st.context.cookies)

    _inject_css()
    _render_sidebar()

    authenticated = (
        st.session_state.mock_mode
        or is_logged_in()
        or is_dev_guest_mode()
    )

    if not authenticated:
        step_login.render()
        return

    sync_usage(st.context.cookies)

    render_topbar(
        mock_mode=st.session_state.mock_mode,
        guest_mode=is_dev_guest_mode(),
        logged_in=is_logged_in(),
    )
    render_stepper(current_step=st.session_state.step)

    step = st.session_state.step
    if step == 1:
        step_business_info.render()
    elif step == 2:
        step_upload.render()
    elif step == 3:
        step_result.render()

    render_footer()


if __name__ == "__main__":
    main()
