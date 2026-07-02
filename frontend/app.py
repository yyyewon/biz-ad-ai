"""
소상공인 두레 - 소상공인을 위한 AI 광고 콘텐츠 생성 서비스
"""
from __future__ import annotations
from pathlib import Path
import streamlit as st

from core.state import init_state
from core.api_client import check_backend_health
from components.layout import render_topbar, render_stepper, render_footer
from components import step_business_info, step_upload, step_result

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


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### ⚙️ 개발 / 데모 설정")
        st.caption("백엔드(A·C·D 담당)가 준비되기 전까지는 목업 모드로 프론트 작업을 이어갈 수 있어요.")

        st.session_state.mock_mode = st.toggle(
            "목업 모드 (백엔드 없이 테스트)",
            value=st.session_state.mock_mode,
        )

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
        if st.button("처음부터 다시 시작", width="stretch"):
            from core.state import reset_all
            reset_all()
            st.rerun()


def main() -> None:
    init_state()
    _inject_css()

    render_topbar(mock_mode=st.session_state.mock_mode)
    _render_sidebar()
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