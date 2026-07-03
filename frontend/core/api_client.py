"""
API 클라이언트 모듈
"""
from __future__ import annotations
import os
import time
import base64
import requests
from typing import Optional

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


def generate_ad(
    store_name: str,
    menu_name: str,
    purpose: str | None,
    request_note: str,
    image_bytes: bytes,
    image_name: str,
    moods: list[str],
    tone: str,
    mock: bool = False,
) -> dict:
    """
    광고 문구 + 이미지 통합 생성
    """
    if mock:
        time.sleep(1.2)
        hashtag_mood = moods[0] if moods else "감성"
        hashtag_purpose = purpose.replace(" ", "").replace("/", "") if purpose else "홍보"
        caption = (
            f"{store_name}의 {menu_name}, 오늘도 한 입이면 반해요 🍽️\n"
            f"{tone} 하루엔 {menu_name} 한 그릇 어떠세요?\n\n"
            f"#{store_name.replace(' ', '')} #{menu_name.replace(' ', '')} "
            f"#{hashtag_mood.replace(' ', '')} #{hashtag_purpose} #맛집스타그램 #오늘뭐먹지"
        )
        return {
            "ok": True,
            "data": {
                "caption": caption,
                "images": [_PLACEHOLDER_PNG] * 3,
            },
        }

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
            GENERATE_ENDPOINT, files=files, data=payload, timeout=REQUEST_TIMEOUT_GENERATE
        )
        res.raise_for_status()
        body = res.json()
        images = [base64.b64decode(b64) for b64 in body.get("images", [])]
        return {
            "ok": True,
            "data": {
                "caption": body.get("caption", ""),
                "images": images,
            },
        }
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "생성이 지연되고 있어요. 잠시 후 다시 시도해 주세요."}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "error": "서버에 연결할 수 없어요. 네트워크 상태를 확인해 주세요."}
    except requests.exceptions.HTTPError:
        return {"ok": False, "error": f"생성에 실패했어요. (서버 응답 코드: {res.status_code})"}
    except requests.exceptions.RequestException:
        return {"ok": False, "error": "알 수 없는 오류로 생성하지 못했어요."}


BACKEND_BASE_URL = os.getenv("BACKEND_API_URL", "http://localhost:8010")

def test_preprocess_image(image_bytes: bytes, filename: str, mime_type: str) -> Optional[bytes]:
    """
    [단위 테스트용] 백엔드 내부 전처리(누끼) 로직의 정상 작동 여부를 검증하기 위한 함수
    """
    url = f"{BACKEND_BASE_URL}/api/v1/image/preprocess"
    files = {"file": (filename, image_bytes, mime_type)}
    
    try:
        response = requests.post(url, files=files, timeout=30)
        
        if response.status_code == 200:
            res_json = response.json()
            image_base64 = res_json.get("data", {}).get("image_base64")
            
            if image_base64:
                # 단위 테스트 성공: 디코딩된 바이너리 리턴
                return base64.b64decode(image_base64)
            raise ValueError("응답 데이터에 'image_base64'가 없습니다.")
        else:
            raise RuntimeError(f"서버 응답 에러 (Status: {response.status_code})")
            
    except Exception as e:
        # 에러 발생 시 화면단으로 에러를 던집니다.
        raise e