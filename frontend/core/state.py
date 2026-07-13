"""
세션 상태 관리 모듈
"""
from __future__ import annotations
import streamlit as st
from core.config import DEV_GUEST_MODE_DEFAULT, MOCK_MODE_DEFAULT

TOTAL_STEPS = 3
STEP_LABELS = ["가게 & 메뉴 정보", "사진 업로드 & 옵션 선택", "생성 결과 확인"]


def init_state() -> None:
    """
    앱 최초 진입 시 1회만 세션 상태 스키마를 만든다
    """
    defaults = {
        "step": 1,
        "business": {"store_name": "", "menu_name": "", "store_location": "", "price": "", "purpose": None},
        "upload": {
            "image_bytes": None,
            "image_name": None,
            "food": None,
            "tone": None,
            "image_request": "",
            "llm_request": "",
        },
        "generation": {
            "status": "idle",       # idle | loading | done | error
            "caption": "",
            "images": [],
            "error_message": "",
            "error_code": None,     # 예: DAILY_LIMIT_EXCEEDED, GENERATION_BUSY 등
        },
        "mock_mode": MOCK_MODE_DEFAULT,

        # 💡 초기 세션 스키마에 refresh_token을 명시해 줍니다.
        "dev_guest_mode": DEV_GUEST_MODE_DEFAULT,
        "auth": {"access_token": None, "refresh_token": None, "user": None},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ---------------------------------------------------------------
# 단계 이동
# ---------------------------------------------------------------
def go_to_step(step: int) -> None:
    st.session_state.step = max(1, min(TOTAL_STEPS, step))


def next_step() -> None:
    go_to_step(st.session_state.step + 1)


def prev_step() -> None:
    go_to_step(st.session_state.step - 1)


# ---------------------------------------------------------------
# 입력값 접근자
# ---------------------------------------------------------------
def set_business_info(store_name: str, menu_name: str, store_location: str, price: str,  purpose: str | None) -> None:
    st.session_state.business = {
        "store_name": store_name.strip(),
        "menu_name": menu_name.strip(),
        "store_location": store_location.strip(),
        "price": price,
        "purpose": purpose,
    }


def is_business_info_valid() -> bool:
    b = st.session_state.business
    return bool(b["store_name"]) and bool(b["menu_name"]) and bool(b["store_location"]) and bool(b["price"]) and b["purpose"] is not None


def set_upload(image_bytes: bytes | None, image_name: str | None) -> None:
    st.session_state.upload["image_bytes"] = image_bytes
    st.session_state.upload["image_name"] = image_name


def set_style(food: str | None, tone: str | None, image_request: str, llm_request: str) -> None:
    st.session_state.upload["food"] = food
    st.session_state.upload["tone"] = tone
    st.session_state.upload["image_request"] = image_request
    st.session_state.upload["llm_request"] = llm_request


def is_upload_step_valid() -> bool:
    u = st.session_state.upload
    return u["image_bytes"] is not None and u["food"] is not None and u["tone"] is not None


# ---------------------------------------------------------------
# 생성 결과
# ---------------------------------------------------------------
def set_generation_loading() -> None:
    st.session_state.generation.update({"status": "loading", "error_message": ""})


def set_generation_error(message: str, code: str | None = None) -> None:
    st.session_state.generation.update(
        {"status": "error", "error_message": message, "error_code": code}
    )


def set_generation_result(caption: str, images: list[dict]) -> None:
    st.session_state.generation.update(
        {"status": "done", "caption": caption, "images": images, "error_message": "", "error_code": None}
    )


def reset_all() -> None:
    """
    처음부터 다시 만들기
    """
    for key in ("business", "upload", "generation", "step"):
        del st.session_state[key]
    init_state()