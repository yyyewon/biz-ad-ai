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
    cookies: dict | None = None, # 토큰 문자열 대신 쿠키 딕셔너리를 전송받음
    mock: bool = False,
) -> dict:
    # ... (기본 Mock 모드 생략) ...

    files = {"image": (image_name or "upload.png", image_bytes, "application/octet-stream")}
    payload = {
        "store_name": store_name,
        "menu_name": menu_name,
        "purpose": purpose,
        "request_note": request_note,
        "moods": ",".join(moods),
        "tone": tone,
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
        fallback, code = "생성에 실패했습니다.", None
        if hasattr(exc, 'response') and exc.response is not None:
            fallback, code = _extract_error(exc.response, f"오류 발생: {exc.response.status_code}")
        return {"ok": False, "error": fallback, "error_code": code}