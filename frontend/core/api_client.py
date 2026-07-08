"""
API 클라이언트 모듈
"""
from __future__ import annotations

import time
import base64
import requests
import streamlit as st

# 💡 토큰 재발급 함수 수입 추가
from core.auth import request_refresh_token
from core.config import (
    TEXT_ENDPOINT,
    IMAGE_ENDPOINT,
    GENERATE_ENDPOINT,
    HEALTH_ENDPOINT,
    REQUEST_TIMEOUT_TEXT,
    REQUEST_TIMEOUT_IMAGE,
    REQUEST_TIMEOUT_GENERATE
)


_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4/P4VAAWlAs1cGcz4AAAAAElFTkSuQmCC"
)


def check_backend_health() -> bool:
    """
    서버 연결 상태 확인
    """
    try:
        res = requests.get(HEALTH_ENDPOINT, timeout=3)
        return res.status_code == 200
    except requests.exceptions.RequestException:
        return False


def _extract_error(res: requests.Response, fallback: str) -> tuple[str, str | None]:
    """
    공통 에러 응답 형식에서 message와 code를 함께 추출
    """
    try:
        body = res.json()
        error = body.get("error") or {}
        message = error.get("message") or fallback
        code = error.get("code")
        return message, code
    except ValueError:
        return fallback, None


def generate_ad(
    store_name: str,
    menu_name: str,
    purpose: str | None,
    request_note: str,
    image_bytes: bytes,
    image_name: str,
    moods: list[str],
    tone: str,
    access_token: str | None = None,
    mock: bool = False,
) -> dict:
    if mock:
        time.sleep(1.2)

        hashtag_mood = moods[0] if moods else "감성"
        hashtag_purpose = purpose.replace(" ", "").replace("/", "") if purpose else "홍보"

        caption = (
            f"{store_name}의 {menu_name}, 오늘도 한 입이면 반해요 ️\n"
            f"{tone} 하루엔 {menu_name} 한 그릇 어떠세요?\n\n"
            f"#{store_name.replace(' ', '')} #{menu_name.replace(' ', '')} "
            f"#{hashtag_mood.replace(' ', '')} #{hashtag_purpose} #맛집스타그램 #오늘뭐먹지"
        )

        return {
            "ok": True,
            "data": {
                "caption": caption,
                "images": [_PLACEHOLDER_PNG] * 3,
                "partial_success": False,
                "warnings": [],
                "image_generation_success": True,
            },
        }

    files = {
        "image": (
            image_name or "upload.png",
            image_bytes,
            "application/octet-stream",
        )
    }

    payload = {
        "store_name": store_name,
        "menu_name": menu_name,
        "purpose": purpose,
        "request_note": request_note,
        "moods": ",".join(moods),
        "tone": tone,
    }

    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}

    try:
        res = requests.post(
            GENERATE_ENDPOINT,
            files=files,
            data=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT_GENERATE,
        )

        # 💡 만약 토큰이 만료되어 401 에러가 났다면 인터셉트하여 리트라이합니다.
        if res.status_code == 401:
            if request_refresh_token():  # 백엔드에 갱신 요청 성공 시
                # 싱싱한 새 Access Token을 다시 세션에서 가져와 헤더를 교체합니다.
                new_token = st.session_state.auth.get("access_token")
                headers["Authorization"] = f"Bearer {new_token}"
                
                # 동일한 요청을 다시 한번 전송합니다 (재시도)
                res = requests.post(
                    GENERATE_ENDPOINT,
                    files=files,
                    data=payload,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT_GENERATE,
                )

        res.raise_for_status()
        body = res.json()

        if body.get("success") is False:
            error = body.get("error") or {}
            return {
                "ok": False,
                "error": error.get("message") or "생성에 실패했어요.",
                "error_code": error.get("code"),
            }

        data = body.get("data") or {}

        if not data and ("caption" in body or "images" in body):
            data = body

        caption = data.get("caption", "")
        image_base64_list = data.get("images") or []
        images: list[bytes] = []

        for image_base64 in image_base64_list:
            if not image_base64:
                continue
            try:
                images.append(base64.b64decode(image_base64))
            except Exception:
                if isinstance(image_base64, str) and "," in image_base64:
                    images.append(base64.b64decode(image_base64.split(",", 1)[1]))

        return {
            "ok": True,
            "data": {
                "caption": caption,
                "images": images,
                "partial_success": data.get("partial_success", False),
                "warnings": data.get("warnings", []),
                "image_generation_success": data.get("image_generation_success"),
                "image_generation": data.get("image_generation"),
            },
        }

    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "error": (
                "생성이 지연되고 있어요. 잠시 후 다시 시도해 주세요. "
                f"(endpoint={GENERATE_ENDPOINT}, timeout={REQUEST_TIMEOUT_GENERATE}s)"
            ),
            "error_code": None,
        }

    except requests.exceptions.ConnectionError:
        return {
            "ok": False,
            "error": "서버에 연결할 수 없어요. 네트워크 상태를 확인해 주세요.",
            "error_code": None,
        }

    except requests.exceptions.HTTPError:
        fallback = f"생성에 실패했어요. (서버 응답 코드: {res.status_code})"
        message, code = _extract_error(res, fallback)
        return {
            "ok": False,
            "error": message,
            "error_code": code,
        }

    except requests.exceptions.RequestException:
        return {
            "ok": False,
            "error": "알 수 없는 오류로 생성하지 못했어요.",
            "error_code": None,
        }