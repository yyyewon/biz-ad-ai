"""
Step 1: 가게 & 메뉴 정보 입력
"""
from __future__ import annotations
import streamlit as st
from core.config import PURPOSE_OPTIONS
from core.state import set_business_info, next_step
from core.auth import is_quota_exceeded, get_daily_usage
from components.ui_kit import quota_exceeded_banner


def render() -> None:
    quota_exceeded = is_quota_exceeded()

    with st.container(border=True):
        st.markdown(
            '<span class="rg-eyebrow">STEP 1</span>'
            '<div class="rg-card-title">어떤 가게의 콘텐츠를 만들까요?</div>'
            '<div class="rg-card-desc">가게/메뉴 이름과 홍보 목적을 알려주시면, 나머지는 AI가 도와드려요.</div>',
            unsafe_allow_html=True,
        )

        if quota_exceeded:
            usage = get_daily_usage() or {}
            quota_exceeded_banner(limit=usage.get("limit"))

        business = st.session_state.business
        # 기존 코드를 지우고 아래 내용으로 교체합니다.
        with st.form("business_info_form", border=False):
            # 💡 개선사항 1: 가게 이름과 대표 메뉴 이름을 가로로 나란히 배치하여 균형감 제공
            col1, col2 = st.columns(2, gap="small")
            with col1:
                store_name = st.text_input(
                    "가게 이름",
                    value=business["store_name"],
                    placeholder="예) 온기식당",  # 더 구체적인 예시로 변경
                    max_chars=30,
                    help="영수증이나 간판에 적힌 상호명을 적어주세요." # 가이드 추가
                )
            with col2:
                menu_name = st.text_input(
                    "대표 메뉴 이름",
                    value=business["menu_name"],
                    placeholder="예) 트러플 크림 파스타",  # 소상공인 친화적 예시로 변경
                    max_chars=30,
                    help="이번에 홍보하고 싶으신 핵심 메뉴를 적어주세요." # 가이드 추가
                )
            
            # 홍보 목적 선택 구역
            st.markdown('<div style="margin-top: 0.5rem;"></div>', unsafe_allow_html=True) # 미세 여백 조절
            purpose = st.pills(
                "홍보 목적",
                options=PURPOSE_OPTIONS,
                selection_mode="single",
                default=business["purpose"],
                key="business_purpose_pills",
            )
            
            # 요청사항 입력 구역
            request_note = st.text_area(
                "요청사항 (선택)",
                value=business["request_note"],
                placeholder="예) 매장 인테리어보다는 음식 자체가 부각되면 좋겠어요.",
                height=90,
                max_chars=200,
            )
            submitted = st.form_submit_button(
                "다음 단계로 →",
                type="primary",
                width="stretch",
                disabled=quota_exceeded,
            )

    if submitted:
        if not store_name.strip() or not menu_name.strip() or purpose is None:
            st.warning("가게 이름, 메뉴 이름, 홍보 목적을 모두 입력해 주세요. (요청사항은 선택 입력이에요)")
            return
        set_business_info(store_name, menu_name, purpose, request_note)
        next_step()
        st.rerun()