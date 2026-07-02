"""
공통 레이아웃 컴포넌트
"""
from __future__ import annotations
import streamlit as st
from core.state import STEP_LABELS, TOTAL_STEPS


def render_topbar(mock_mode: bool) -> None:
    status = "🧪 목업 모드" if mock_mode else "🟢 서버 연결"
    html = (
        '<div class="rg-topbar">'
        '<div>'
        '<div class="rg-logo">소상공인 두레</div>'
        '<div class="rg-tagline">사장님의 인스타그램, 사진 한 장이면 완성돼요</div>'
        '</div>'
        f'<div class="rg-tagline">{status}</div>'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_stepper(current_step: int) -> None:
    items_html = []
    for idx, label in enumerate(STEP_LABELS, start=1):
        if idx < current_step:
            state, marker = "done", "✓"
        elif idx == current_step:
            state, marker = "active", str(idx)
        else:
            state, marker = "", str(idx)
        items_html.append(
            f'<div class="rg-step {state}">'
            f'<div class="rg-step-num">{marker}</div>'
            f'<div class="rg-step-label">{label}</div>'
            f'</div>'
        )
    st.markdown(f'<div class="rg-stepper">{"".join(items_html)}</div>', unsafe_allow_html=True)


def render_footer() -> None:
    step = st.session_state.get("step", 1)
    html = (
        '<div class="rg-footer">'
        f'소상공인 두레 · 소상공인을 위한 AI 광고 콘텐츠 생성 서비스 · Step {step}/{TOTAL_STEPS}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)
