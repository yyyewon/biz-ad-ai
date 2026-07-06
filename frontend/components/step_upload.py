"""
Step 2: 사진 업로드 & 무드/톤 선택
"""
from __future__ import annotations
import streamlit as st
from core.config import MOOD_OPTIONS, TONE_OPTIONS, MAX_UPLOAD_MB, ALLOWED_IMAGE_TYPES
from core.state import set_upload, set_style, is_upload_step_valid, next_step, prev_step
from core.auth import is_quota_exceeded, get_daily_usage
from components.ui_kit import phone_preview, quota_exceeded_banner


def render() -> None:
    quota_exceeded = is_quota_exceeded()

    left, right = st.columns(2, gap="medium")

    with left:
        with st.container(border=True):
            st.markdown(
                '<span class="rg-eyebrow">STEP 2</span>'
                '<div class="rg-card-title">음식 사진과 원하는 무드를 알려주세요</div>'
                '<div class="rg-card-desc">배경은 AI가 새 배경으로 자연스럽게 바꿔드려요. 원본 음식은 그대로 유지됩니다.</div>',
                unsafe_allow_html=True,
            )

            if quota_exceeded:
                usage = get_daily_usage() or {}
                quota_exceeded_banner(limit=usage.get("limit"))

            uploaded_file = st.file_uploader(
                "음식 사진 업로드",
                type=ALLOWED_IMAGE_TYPES,
                help=f"최대 {MAX_UPLOAD_MB}MB, JPG/PNG/WEBP 지원",
            )
            if uploaded_file is not None:
                image_bytes = uploaded_file.getvalue()
                size_mb = len(image_bytes) / (1024 * 1024)
                if size_mb > MAX_UPLOAD_MB:
                    st.error(f"파일이 너무 커요 ({size_mb:.1f}MB). {MAX_UPLOAD_MB}MB 이하로 올려주세요.")
                else:
                    set_upload(image_bytes, uploaded_file.name)

            moods = st.pills(
                "원하는 인스타 무드 (복수 선택 가능)",
                options=MOOD_OPTIONS,
                selection_mode="multi",
                default=st.session_state.upload["moods"],
                key="upload_moods_pills",
            )

            tone = st.segmented_control(
                "문구 톤앤매너",
                options=TONE_OPTIONS,
                selection_mode="single",
                default=st.session_state.upload["tone"],
                key="upload_tone_select",
            )

            set_style(moods or [], tone)

            nav_left, nav_right = st.columns(2)
            with nav_left:
                if st.button("← 이전", type="secondary", width="stretch"):
                    prev_step()
                    st.rerun()
            with nav_right:
                if st.button(
                    "다음 단계로 →",
                    type="primary",
                    width="stretch",
                    disabled=quota_exceeded,
                ):
                    if not is_upload_step_valid():
                        st.warning("사진 업로드, 무드, 톤을 모두 선택해 주세요.")
                    else:
                        next_step()
                        st.rerun()

    with right:
        with st.container(border=True):
            st.markdown(
                '<div class="rg-card-title" style="text-align:center;">업로드한 사진</div>',
                unsafe_allow_html=True,
            )
            image_bytes = st.session_state.upload["image_bytes"]
            caption = (
                "다음 단계에서 AI가 배경과 문구를 새로 만들어드려요 ✨"
                if image_bytes
                else ""
            )
            phone_preview(
                store_name=st.session_state.business["store_name"],
                caption=caption,
                hero_image_bytes=image_bytes,
                placeholder_label="사진을 업로드해 주세요",
            )