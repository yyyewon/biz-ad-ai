"""
Step 1: 가게 & 메뉴 정보 입력
"""
from __future__ import annotations
import streamlit as st
from core.config import PURPOSE_OPTIONS
from core.state import set_business_info, next_step
from core.auth import is_quota_exceeded, get_daily_usage, is_logged_in, save_business_info
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
        form_epoch = st.session_state.get("business_form_epoch", 0)

        with st.form(f"business_info_form_{form_epoch}", border=False):
            row1_col1, row1_col2 = st.columns(2, gap="small")
            with row1_col1:
                store_name = st.text_input(
                    "가게 이름",
                    value=business["store_name"],
                    placeholder="예) 온기식당",
                    max_chars=30,
                    help="영수증이나 간판에 적힌 상호명을 적어주세요."
                )
            with row1_col2:
                menu_name = st.text_input(
                    "대표 메뉴 이름",
                    value=business["menu_name"],
                    placeholder="예) 트러플 크림 파스타",
                    max_chars=20,
                    help="이번에 홍보하고 싶으신 핵심 메뉴를 적어주세요."
                )
            
            row2_col1, row2_col2 = st.columns(2, gap="small")
            with row2_col1:
                store_location = st.text_input(
                    "가게 위치",
                    value=business["store_location"],
                    placeholder="예) 서울시 강서구",
                    max_chars=30,
                    help="가게 위치를 적어주세요",
                )
            with row2_col2:
                price = st.text_input(
                    "가격",
                    value=business["price"],
                    placeholder="예) 10000원",
                    max_chars=30,
                )

            st.markdown('<div style="margin-top: 0.5rem;"></div>', unsafe_allow_html=True)
            purpose = st.pills(
                "홍보 목적",
                options=PURPOSE_OPTIONS,
                selection_mode="single",
                default=business["purpose"],
                key="business_purpose_pills",
            )

            submitted = st.form_submit_button(
                "다음 단계로 →",
                type="primary",
                width="stretch",
                disabled=quota_exceeded,
            )

    if submitted:
        if (
            not store_name.strip()
            or not menu_name.strip()
            or not store_location.strip()
            or not price.strip()
            or purpose is None
        ):
            st.warning("가게 이름, 메뉴 이름, 위치, 가격, 홍보 목적을 모두 입력해 주세요.")
            return
        set_business_info(store_name, menu_name, store_location, price, purpose)

        if is_logged_in():
            save_business_info(
                cookies=st.context.cookies,
                store_name=store_name.strip(),
                store_location=store_location.strip(),
            )

        next_step()
        st.rerun()
