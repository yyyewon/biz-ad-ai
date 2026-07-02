"""
API 클라이언트 모듈
"""
from __future__ import annotations
import time
import base64
import requests

from core.config import (
    TEXT_ENDPOINT,
    IMAGE_ENDPOINT,
    HEALTH_ENDPOINT,
    REQUEST_TIMEOUT_TEXT,
    REQUEST_TIMEOUT_IMAGE,
)


_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4/P4VAAWlAs1cGcz4AAAAAElFTkSuQmCC"
)


def check_backend_health() -> bool:
    """서버 연결 상태를 가볍게 확인한다. 실패해도 앱은 죽지 않고 False만 반환."""
    try:
        res = requests.get(HEALTH_ENDPOINT, timeout=3)
        return res.status_code == 200
    except requests.exceptions.RequestException:
        return False


def generate_ad_text(
    store_name: str,
    menu_name: str,
    moods: list[str],
    tone: str,
    purpose: str | None = None,
    request_note: str = "",
    mock: bool = False,
) -> dict:
    """
    광고 문구 생성
    """
    if mock:
        time.sleep(0.6)
        hashtag_mood = moods[0] if moods else "감성"
        hashtag_purpose = purpose.replace(" ", "").replace("/", "") if purpose else "홍보"
        caption = (
            f"{store_name}의 {menu_name}, 오늘도 한 입이면 반해요 🍽️\n"
            f"{tone} 하루엔 {menu_name} 한 그릇 어떠세요?\n\n"
            f"#{store_name.replace(' ', '')} #{menu_name.replace(' ', '')} "
            f"#{hashtag_mood.replace(' ', '')} #{hashtag_purpose} #맛집스타그램 #오늘뭐먹지"
        )
        return {"ok": True, "data": {"caption": caption}}

    payload = {
        "store_name": store_name,
        "menu_name": menu_name,
        "moods": moods,
        "tone": tone,
        "purpose": purpose,
        "request_note": request_note,
    }
    try:
        res = requests.post(TEXT_ENDPOINT, json=payload, timeout=REQUEST_TIMEOUT_TEXT)
        res.raise_for_status()
        return {"ok": True, "data": res.json()}
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "문구 생성이 지연되고 있어요. 잠시 후 다시 시도해 주세요."}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "error": "서버에 연결할 수 없어요. 네트워크 상태를 확인해 주세요."}
    except requests.exceptions.HTTPError:
        return {"ok": False, "error": f"문구 생성에 실패했어요. (서버 응답 코드: {res.status_code})"}
    except requests.exceptions.RequestException:
        return {"ok": False, "error": "알 수 없는 오류로 문구를 생성하지 못했어요."}


def generate_ad_image(
    image_bytes: bytes,
    image_name: str,
    moods: list[str],
    tone: str,
    mock: bool = False,
) -> dict:
    """
    광고 이미지 합성
    """
    if mock:
        time.sleep(1.0)
        return {"ok": True, "data": {"images": [_PLACEHOLDER_PNG] * 3}}

    files = {"image": (image_name or "upload.png", image_bytes, "application/octet-stream")}
    payload = {"moods": ",".join(moods), "tone": tone}
    try:
        res = requests.post(
            IMAGE_ENDPOINT, files=files, data=payload, timeout=REQUEST_TIMEOUT_IMAGE
        )
        res.raise_for_status()
        body = res.json()
        images = [base64.b64decode(b64) for b64 in body.get("images", [])]
        return {"ok": True, "data": {"images": images}}
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "이미지 생성이 예상보다 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요."}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "error": "서버에 연결할 수 없어요. 네트워크 상태를 확인해 주세요."}
    except requests.exceptions.HTTPError:
        return {"ok": False, "error": f"이미지 생성에 실패했어요. (서버 응답 코드: {res.status_code})"}
    except requests.exceptions.RequestException:
        return {"ok": False, "error": "알 수 없는 오류로 이미지를 생성하지 못했어요."}