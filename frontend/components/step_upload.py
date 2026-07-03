"""
Step 2: 사진 업로드 & 무드/톤 선택 (백엔드 API 연동 버전)
"""
from __future__ import annotations
import base64  # 💡 백엔드의 base64 응답 복원을 위해 추가
import requests  # 💡 백엔드 API 통신을 위해 추가
import streamlit as st
from core.config import MOOD_OPTIONS, TONE_OPTIONS, MAX_UPLOAD_MB, ALLOWED_IMAGE_TYPES
from core.state import set_upload, set_style, is_upload_step_valid, next_step, prev_step
from components.ui_kit import phone_preview


def render() -> None:
    left, right = st.columns(2, gap="medium")

    with left:
        with st.container(border=True):
            st.markdown(
                '<span class="rg-eyebrow">STEP 2</span>'
                '<div class="rg-card-title">음식 사진과 원하는 무드를 알려주세요</div>'
                '<div class="rg-card-desc">배경은 AI가 새 배경으로 자연스럽게 바꿔드려요. 원본 음식은 그대로 유지됩니다.</div>',
                unsafe_allow_html=True,
            )

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
                    # 💡 파일 이름이 세션 상태에 저장된 것과 다를 때만 API 요청 수행 (중복 호출 방지)
                    if st.session_state.upload.get("filename") != uploaded_file.name:
                        with st.spinner("🧙 AI가 음식 이미지를 선명하게 추출하고 있습니다..."):
                            try:
                                # 백엔드 라우터 구조 반영 (POST /api/v1/image/preprocess)
                                API_URL = "http://34.60.252.165:8010/api/v1/image/preprocess"
                                files = {"file": (uploaded_file.name, image_bytes, uploaded_file.type)}
                                
                                response = requests.post(API_URL, files=files)
                                
                                if response.status_code == 200:
                                    res_json = response.json()
                                    # 팀원분의 공통 성공 응답 뼈대(success_response) 구조 파싱
                                    data = res_json.get("data", {})
                                    image_base64 = data.get("image_base64")
                                    
                                    if image_base64:
                                        # base64 string을 다시 bytes 바이너리로 변환
                                        processed_image_bytes = base64.b64decode(image_base64)
                                        # 전처리 완료된 이미지 데이터를 세션 상태에 세팅
                                        set_upload(processed_image_bytes, uploaded_file.name)
                                        st.rerun()
                                    else:
                                        st.error("❌ 전처리 이미지 데이터가 응답에 포함되어 있지 않습니다.")
                                else:
                                    # 백엔드 팀원이 설계한 AppException 공통 에러 메시지 노출
                                    try:
                                        error_msg = response.json().get("message", "알 수 없는 오류가 발생했습니다.")
                                    except:
                                        error_msg = f"HTTP {response.status_code} 에러"
                                    st.error(f"❌ AI 전처리 실패: {error_msg}")
                                    
                            except requests.exceptions.ConnectionError:
                                st.error("🔌 백엔드 API 서버(Port 8010)와 통신할 수 없습니다. 서버 실행 상태를 확인해 주세요.")
                            except Exception as e:
                                st.error(f"⚠️ 시스템 연동 에러 발생: {e}")

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
                if st.button("다음 단계로 →", type="primary", width="stretch"):
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