"""
Step 2: 사진 업로드 & 무드/톤 선택 (백엔드 연동 및 UX 개선 통합 버전)
"""
from __future__ import annotations
import streamlit as st
from core.config import MOOD_OPTIONS, TONE_OPTIONS, MAX_UPLOAD_MB, ALLOWED_IMAGE_TYPES
from core.auth import get_daily_usage, is_quota_exceeded
from core.state import set_upload, set_style, is_upload_step_valid, next_step, prev_step
from components.ui_kit import phone_preview, quota_exceeded_banner


def render() -> None:

    quota_exceeded = is_quota_exceeded()
    if quota_exceeded:
        usage = get_daily_usage() or {}
        quota_exceeded_banner(limit=usage.get("limit"))
    left, right = st.columns(2, gap="medium")

    with left:
        with st.container(border=True):
            st.markdown(
                '<span class="rg-eyebrow">STEP 2</span>'
                '<div class="rg-card-title">음식 사진과 원하는 무드를 알려주세요</div>'
                '<div class="rg-card-desc">배경은 AI가 새 배경으로 자연스럽게 바꿔드려요. 원본 음식은 그대로 유지됩니다.</div>',
                unsafe_allow_html=True,
            )

            # 💡 개선사항 2: 업로드 박스 안내 타이틀 한글화 및 label_visibility 적용
            st.markdown("**음식 사진 업로드**", help=f"최대 {MAX_UPLOAD_MB}MB, JPG/PNG/WEBP 포맷의 선명한 사진을 올려주세요.")
            uploaded_file = st.file_uploader(
                "음식 사진 업로드",
                type=ALLOWED_IMAGE_TYPES,
                label_visibility="collapsed",  # 기본 영어 라벨을 가리고 커스텀 라벨을 돋보이게 합니다.
            )
            
            # 사장님들을 위한 팁 자막 추가
            if uploaded_file is None:
                st.caption("💡 **Tip**: 음식 테두리가 뚜렷하고 밝게 나온 사진일수록 AI가 배경을 훨씬 깔끔하고 예쁘게 바꿔드려요! (누끼 선명도 Up)")
            
            # ------------------ 💡 공통 함수 호출 구조 및 키값 동기화 ------------------
            if uploaded_file is not None:
                image_bytes = uploaded_file.getvalue()
                size_mb = len(image_bytes) / (1024 * 1024)
                if size_mb > MAX_UPLOAD_MB:
                    st.error(f"파일이 너무 커요 ({size_mb:.1f}MB). {MAX_UPLOAD_MB}MB 이하로 올려주세요.")
                else:
                    # 💡 충돌 해결: 최신 메인 브랜치의 "image_name" 키값을 존중하면서 중복 rerun을 방지합니다.
                    if st.session_state.upload.get("image_name") != uploaded_file.name:
                        set_upload(image_bytes, uploaded_file.name)
                        st.rerun()
            # ----------------------------------------------------------------------------------

            # 💡 개선사항 1: 인스타 무드 라벨 문구 수정 (최대 2개 제한 가이드 제공)
            moods = st.pills(
                "원하는 인스타 무드 (최대 2개 선택 가능)",
                options=MOOD_OPTIONS,
                selection_mode="multi",
                default=st.session_state.upload["moods"],
                key="upload_moods_pills",
            )

            # 무드 3개 이상 선택 시 경고 및 브레이크 플래그 설정
            is_mood_invalid = len(moods) > 2
            if is_mood_invalid:
                st.warning("⚠️ 무드는 최대 2개까지만 선택하실 수 있어요! 가장 잘 어울리는 무드 2개를 골라주세요.")

            tone = st.segmented_control(
                "문구 톤앤매너",
                options=TONE_OPTIONS,
                selection_mode="single",
                # 세션 상태에 값이 없을 때 에러가 나거나 풀리지 않도록 기본값을 안전하게 세팅
                default=st.session_state.upload.get("tone", TONE_OPTIONS[0]), 
                key="upload_tone_select",
            )

            nav_left, nav_right = st.columns(2)
            with nav_left:
                if st.button("← 이전", type="secondary", width="stretch"):
                    prev_step()
                    st.rerun()
            with nav_right:
                # 무드를 3개 이상 선택했다면 다음 단계로 가는 버튼을 비활성화(disabled)하여 원천 차단합니다.
                if st.button("다음 단계로 →", type="primary", width="stretch", disabled=is_mood_invalid):
                    # 💡 순서 제어 버그 수정: 버튼 클릭 직후 최종 입력값을 상태에 확실히 강제 주입
                    set_style(moods or [], tone)
                    
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