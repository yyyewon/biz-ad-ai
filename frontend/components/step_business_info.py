"""
Step 1: 가게 & 메뉴 정보 입력 (백엔드 연동 및 UX 개선 통합 버전)
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
            # 💡 개선사항 1: 가게 이름과 대표 메뉴 이름을 가로로 나란히 배치하여 균형감 제공
            col1, col2 = st.columns(2, gap="small")
            with col1:
                store_name = st.text_input(
                    "가게 이름",
                    value=business["store_name"],
                    placeholder="예) 온기식당",
                    max_chars=30,
                    help="영수증이나 간판에 적힌 상호명을 적어주세요."
                )
            with col2:
                menu_name = st.text_input(
                    "대표 메뉴 이름",
                    value=business["menu_name"],
                    placeholder="예) 트러플 크림 파스타",
                    max_chars=30,
                    help="이번에 홍보하고 싶으신 핵심 메뉴를 적어주세요."
                )
            
            # 홍보 목적 선택 구역 (다중 선택 개선 ✨)
            st.markdown('<div style="margin-top: 0.5rem;"></div>', unsafe_allow_html=True) # 미세 여백 조절
            
            # 복수 선택 시 default 값은 리스트 형태여야 하므로, 만약 기존 값이 단일 문자열이라면 리스트로 감싸줍니다.
            default_purpose = business["purpose"] if isinstance(business["purpose"], list) else [business["purpose"]] if business["purpose"] else []
            
            purposes = st.pills(
                "홍보 목적 (복수 선택 가능)",
                options=PURPOSE_OPTIONS,
                selection_mode="multi",  # 단일 선택("single")에서 다중 선택("multi")으로 전환!
                default=default_purpose,
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
            submitted = st.form_submit_button("다음 단계로 →", type="primary", width="stretch")

    if submitted:
        # 다중 선택으로 바뀌었으므로, 아무것도 선택하지 않았을 때(리스트가 빌 때)를 검증합니다.
        if not store_name.strip() or not menu_name.strip() or not purposes:
            st.warning("가게 이름, 메뉴 이름, 홍보 목적을 최소 하나 이상 선택해 주세요. (요청사항은 선택 입력이에요)")
            return
            
        # 선택된 목적 리스트(purposes)를 그대로 상태 저장소에 저장합니다.
        set_business_info(store_name, menu_name, purposes, request_note)
        next_step()
        st.rerun()