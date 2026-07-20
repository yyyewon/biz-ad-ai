"""
세션 상태 관리 모듈
"""
from __future__ import annotations
import streamlit as st
from core.config import DEV_GUEST_MODE_DEFAULT, MOCK_MODE_DEFAULT

TOTAL_STEPS = 3
STEP_LABELS = ["가게 & 메뉴 정보", "사진 업로드 & 옵션 선택", "생성 결과 확인"]


# ---------------------------------------------------------------
# Query param 기반 영속화 (새로고침/북마크 대응)
# ---------------------------------------------------------------
def _save_business_to_query_params() -> None:
    """가게 이름/위치를 URL query param에 저장해 새로고침 시 복원 가능하게 한다."""
    b = st.session_state.get("business") or {}
    store_name = (b.get("store_name") or "").strip()
    store_location = (b.get("store_location") or "").strip()
    for key, value in (
        ("store_name", store_name),
        ("store_location", store_location),
    ):
        if value:
            st.query_params[key] = value
        elif key in st.query_params:
            # DB 값이 비어 있는데 URL에 예전 값이 남아 다시 복원되는 것을 막는다.
            del st.query_params[key]


def _restore_business_from_query_params() -> None:
    """URL query param에서 가게 이름/위치를 복원한다."""
    qp = st.query_params
    store_name = qp.get("store_name")
    store_location = qp.get("store_location")
    if store_name or store_location:
        business = st.session_state.get("business") or {}
        if not business.get("store_name") and store_name:
            business["store_name"] = store_name
        if not business.get("store_location") and store_location:
            business["store_location"] = store_location
        st.session_state.business = business


def _save_local_generation_count() -> None:
    """목업/게스트 모드용 로컬 생성 횟수를 query param에 저장한다."""
    count = st.session_state.get("local_generation_count", 0)
    st.query_params["local_gen_count"] = str(count)


def _restore_local_generation_count() -> None:
    """query param에서 로컬 생성 횟수를 복원한다."""
    qp = st.query_params
    raw = qp.get("local_gen_count")
    if raw:
        try:
            st.session_state.local_generation_count = int(raw)
        except (ValueError, TypeError):
            st.session_state.local_generation_count = 0
    else:
        st.session_state.local_generation_count = 0


def persist_state() -> None:
    """새로고침 대비: 현재 상태를 query param에 저장한다."""
    _save_business_to_query_params()
    _save_local_generation_count()


def restore_state() -> None:
    """새로고침 후: query param에서 상태를 복원한다."""
    _restore_business_from_query_params()
    _restore_local_generation_count()


# ---------------------------------------------------------------
# 세션 상태 초기화
# ---------------------------------------------------------------
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

        "dev_guest_mode": DEV_GUEST_MODE_DEFAULT,
        "auth": {"access_token": None, "refresh_token": None, "user": None},
        # Step 1 폼 remount용 — reset 시 증가시켜 저장된 가게 이름/위치가 폼에 다시 반영되게 한다.
        "business_form_epoch": 0,
        # 목업/게스트 모드용 로컬 생성 횟수
        "local_generation_count": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # query param에서 복원 (init_state 후에 호출되어야 함)
    restore_state()


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
    # 입력 즉시 query param에 저장 (새로고침 대비)
    _save_business_to_query_params()


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


def increment_local_generation_count() -> None:
    """목업/게스트 모드에서 로컬 생성 횟수를 1 증가시키고 query param에 저장한다."""
    count = st.session_state.get("local_generation_count", 0) + 1
    st.session_state.local_generation_count = count
    _save_local_generation_count()


def get_local_generation_count() -> int:
    return st.session_state.get("local_generation_count", 0)


def reset_all() -> None:
    """
    처음부터 다시 만들기

    가게 이름·위치는 세션/DB에 저장된 값을 유지하고, 나머지 입력·생성 결과만 초기화한다.
    """
    preserved_name = (st.session_state.get("business") or {}).get("store_name", "").strip()
    preserved_location = (st.session_state.get("business") or {}).get("store_location", "").strip()

    for key in ("business", "upload", "generation", "step", "edited_caption"):
        st.session_state.pop(key, None)

    init_state()
    st.session_state.business_form_epoch = st.session_state.get("business_form_epoch", 0) + 1

    from core.auth import apply_saved_business_info, is_logged_in, refresh_me

    cookies = getattr(st.context, "cookies", None) or {}
    if is_logged_in() and cookies:
        refresh_me(cookies)

    apply_saved_business_info()

    if preserved_name:
        st.session_state.business["store_name"] = preserved_name
    if preserved_location:
        st.session_state.business["store_location"] = preserved_location
