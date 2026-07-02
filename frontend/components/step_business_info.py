"""
Step 1: 가게 & 메뉴 정보 입력
"""
from __future__ import annotations
import streamlit as st
from core.config import PURPOSE_OPTIONS
from core.state import set_business_info, next_step


def render() -> None:
    with st.container(border=True):
        st.markdown(
            '<span class="rg-eyebrow">STEP 1</span>'
            '<div class="rg-card-title">어떤 가게의 콘텐츠를 만들까요?</div>'
            '<div class="rg-card-desc">가게/메뉴 이름과 홍보 목적을 알려주시면, 나머지는 AI가 도와드려요.</div>',
            unsafe_allow_html=True,
        )

        business = st.session_state.business
        with st.form("business_info_form", border=False):
            store_name = st.text_input(
                "가게 이름",
                value=business["store_name"],
                placeholder="예) 온기식당",
                max_chars=30,
            )
            menu_name = st.text_input(
                "대표 메뉴 이름",
                value=business["menu_name"],
                placeholder="예) 트러플 크림 파스타",
                max_chars=30,
            )
            purpose = st.pills(
                "홍보 목적",
                options=PURPOSE_OPTIONS,
                selection_mode="single",
                default=business["purpose"],
                key="business_purpose_pills",
            )
            request_note = st.text_area(
                "요청사항 (선택)",
                value=business["request_note"],
                placeholder="예) 매장 인테리어보다는 음식 자체가 부각되면 좋겠어요.",
                height=90,
                max_chars=200,
            )
            submitted = st.form_submit_button("다음 단계로 →", type="primary", width="stretch")

    if submitted:
        if not store_name.strip() or not menu_name.strip() or purpose is None:
            st.warning("가게 이름, 메뉴 이름, 홍보 목적을 모두 입력해 주세요. (요청사항은 선택 입력이에요)")
            return
        set_business_info(store_name, menu_name, purpose, request_note)
        next_step()
        st.rerun()