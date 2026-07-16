"""
API 클라이언트 모듈
"""
from __future__ import annotations

import time
import base64
import requests
import streamlit as st

from core.auth import request_refresh_token
from core.config import (
    GENERATE_ENDPOINT,
    HEALTH_ENDPOINT,
    REQUEST_TIMEOUT_GENERATE,
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
    image_bytes: bytes,
    image_name: str,
    food: str,
    tone: str,
    image_request: str,
    llm_request: str,
    price: str = "",
    store_location: str = "",
    cookies: dict | None = None,
    mock: bool = False,
) -> dict:
    if mock:
        time.sleep(1.2)

        hashtag_food = food if food else "맛집"
        hashtag_purpose = purpose.replace(" ", "").replace("/", "") if purpose else "홍보"

        caption = (
            f"{store_name}의 {menu_name}, 오늘도 한 입이면 반해요\n"
            f"{llm_request.strip() + chr(10) if llm_request and llm_request.strip() else ''}"
            f"{tone} 톤으로 {menu_name} 한 그릇 어떠세요?\n\n"
            f"#{store_name.replace(' ', '')} #{menu_name.replace(' ', '')} "
            f"#{hashtag_food.replace(' ', '')} #{hashtag_purpose} #맛집스타그램 #오늘뭐먹지"
        )

        return {
            "ok": True,
            "data": {
                "caption": f"✨ [{store_name}]의 신메뉴 '{menu_name}' 출시! ✨\n\n{purpose or '홍보'}를 위해 정성껏 준비했습니다. \n지금 바로 매장에서 만나보세요! #소상공인두레",
                "images": [image_bytes if image_bytes else _PLACEHOLDER_PNG],
                "partial_success": False,
                "warnings": [],
                "image_generation_success": True,
                "image_generation": {"status": "SUCCESS"},
            },
        }


    files = {"image": (image_name or "upload.png", image_bytes, "application/octet-stream")}
    payload = {
        "store_name": store_name,
        "menu_name": menu_name,
        "purpose": purpose,
        "llm_request": llm_request,
        "food": food,
        "tone": tone,
        "price": price,
        "store_location": store_location,
        "image_request": image_request,
    }
    try:
        res = requests.post(
            GENERATE_ENDPOINT,
            files=files,
            data=payload,
            cookies=cookies,
            timeout=REQUEST_TIMEOUT_GENERATE,
        )

        if res.status_code == 401:
            if request_refresh_token(cookies):
                res = requests.post(
                    GENERATE_ENDPOINT,
                    files=files,
                    data=payload,
                    cookies=cookies,
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

    except requests.exceptions.RequestException as exc:
        fallback = "서버에 연결할 수 없어요. 네트워크 상태를 확인해 주세요."
        code = "NETWORK_DISCONNECTED"
        
        if hasattr(exc, 'response') and exc.response is not None:
            status_code = exc.response.status_code
            if status_code in [502, 503, 504]:
                fallback = f"서버가 응답하지 않습니다. 잠시 후 다시 시도해 주세요. (오류 코드: {status_code})"
                code = f"SERVER_{status_code}"
            else:
                fallback, code = _extract_error(exc.response, f"오류 발생: {status_code}")
                
        return {"ok": False, "error": fallback, "error_code": code}