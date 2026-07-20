"""
API 클라이언트 모듈
"""
from __future__ import annotations

import json
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


def _decode_images(image_base64_list: list) -> list[bytes]:
    """base64 문자열 목록을 bytes 목록으로 변환한다."""
    images: list[bytes] = []
    for image_base64 in image_base64_list:
        if not image_base64:
            continue
        try:
            images.append(base64.b64decode(image_base64))
        except Exception:
            if isinstance(image_base64, str) and "," in image_base64:
                images.append(base64.b64decode(image_base64.split(",", 1)[1]))
    return images


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
    on_stage=None,
) -> dict:
    """
    통합 광고 생성을 SSE로 요청한다.

    on_stage:
        진행 단계 이벤트(text/image 트랙 상태)를 수신할 때마다 호출되는 콜백.
        시그니처: on_stage(event: dict) -> None
        별도 스레드에서 호출되므로, 호출부는 st.session_state를 통해 메인 스레드로 상태를 전달한다.

    반환값:
        - 성공: {"ok": True, "data": {caption, images, ...}}
        - 실패: {"ok": False, "error": str, "error_code": str | None}
    """
    if mock:
        simulate_failure = bool(st.session_state.get("simulate_image_failure"))
        return _generate_ad_mock(
            store_name=store_name,
            menu_name=menu_name,
            purpose=purpose,
            image_bytes=image_bytes,
            food=food,
            tone=tone,
            llm_request=llm_request,
            on_stage=on_stage,
            simulate_image_failure=simulate_failure,
        )

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
        res = _post_generate_sse(files, payload, cookies)
        if res is None:
            return {"ok": False, "error": "인증 세션이 만료됐어요. 다시 로그인해 주세요.", "error_code": "UNAUTHORIZED"}

        # SSE 응답이 아닌 일반 에러 응답(예: 4xx/5xx) 처리
        content_type = res.headers.get("content-type", "")
        if "text/event-stream" not in content_type:
            return _handle_non_sse_error(res)

        # event-stream 파싱
        for raw_line in res.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            payload_str = line[len("data:"):].strip()
            if not payload_str:
                continue
            try:
                event = json.loads(payload_str)
            except json.JSONDecodeError:
                continue

            kind = event.get("event")
            if kind == "result":
                return _build_result(event.get("data") or {})
            if kind == "error":
                return {
                    "ok": False,
                    "error": event.get("message") or "생성에 실패했어요.",
                    "error_code": event.get("code"),
                }
            if kind == "stage" and on_stage is not None:
                try:
                    on_stage(event)
                except Exception:
                    # 진행 표시용 콜백 실패가 생성 흐름을 깨면 안 된다.
                    pass

        # 스트림이 종료 이벤트 없이 끝난 경우
        return {"ok": False, "error": "서버 응답이 중간에 끊겼어요. 다시 시도해 주세요.", "error_code": "STREAM_INCOMPLETE"}

    except requests.exceptions.RequestException as exc:
        fallback = "서버에 연결할 수 없어요. 네트워크 상태를 확인해 주세요."
        code = "NETWORK_DISCONNECTED"

        if hasattr(exc, "response") and exc.response is not None:
            status_code = exc.response.status_code
            if status_code in [502, 503, 504]:
                fallback = f"서버가 응답하지 않습니다. 잠시 후 다시 시도해 주세요. (오류 코드: {status_code})"
                code = f"SERVER_{status_code}"
            else:
                fallback, code = _extract_error(exc.response, f"오류 발생: {status_code}")

        return {"ok": False, "error": fallback, "error_code": code}


def _post_generate_sse(files: dict, payload: dict, cookies: dict | None) -> requests.Response | None:
    """
    SSE 스트리밍 요청을 보낸다. 401이면 토큰 재발급 후 1회 재시도한다.
    """
    res = requests.post(
        GENERATE_ENDPOINT,
        files=files,
        data=payload,
        cookies=cookies,
        timeout=REQUEST_TIMEOUT_GENERATE,
        stream=True,
    )

    if res.status_code == 401:
        if request_refresh_token(cookies):
            res = requests.post(
                GENERATE_ENDPOINT,
                files=files,
                data=payload,
                cookies=cookies,
                timeout=REQUEST_TIMEOUT_GENERATE,
                stream=True,
            )
        else:
            return None

    res.raise_for_status()
    return res


def _handle_non_sse_error(res: requests.Response) -> dict:
    """SSE가 아닌 에러 응답(레거시 JSON 에러 등)을 처리한다."""
    try:
        body = res.json()
        if body.get("success") is False:
            error = body.get("error") or {}
            return {
                "ok": False,
                "error": error.get("message") or "생성에 실패했어요.",
                "error_code": error.get("code"),
            }
    except ValueError:
        pass
    return {
        "ok": False,
        "error": f"오류 발생: {res.status_code}",
        "error_code": f"HTTP_{res.status_code}",
    }


def _build_result(data: dict) -> dict:
    """
    result 이벤트의 data를 프론트엔드용 결과 dict로 변환한다.

    요청3: 이미지 생성에 실패한 경우(partial_success 또는 images가 비어 있음)는
    원본 노출 대신 일관된 실패 처리(에러 메시지 + 재시도/이전 단계)로 보낸다.
    """
    images_b64 = data.get("images") or []
    images = _decode_images(images_b64)
    image_generation_success = data.get("image_generation_success")

    # 이미지 생성이 명시적으로 실패했거나 결과 이미지가 없으면 실패로 취급한다.
    if image_generation_success is False or not images:
        return {
            "ok": False,
            "error": data.get("image_generation_error") or "이미지 생성에 실패했어요. 잠시 후 다시 시도해 주세요.",
            "error_code": "IMAGE_GENERATION_FAILED",
        }

    return {
        "ok": True,
        "data": {
            "caption": data.get("caption", ""),
            "images": images,
            "partial_success": data.get("partial_success", False),
            "warnings": data.get("warnings", []),
            "image_generation_success": image_generation_success,
            "image_generation": data.get("image_generation"),
        },
    }


def _generate_ad_mock(
    *,
    store_name: str,
    menu_name: str,
    purpose: str | None,
    image_bytes: bytes,
    food: str,
    tone: str,
    llm_request: str,
    on_stage=None,
    simulate_image_failure: bool = False,
) -> dict:
    """mock 모드: 가짜 단계 이벤트를 흘려보낸 뒤 더미 결과를 반환한다."""
    stages = [
        {"event": "stage", "track": "text", "status": "start", "label": "광고 문구를 생성 중이에요"},
        {"event": "stage", "track": "image", "status": "start", "label": "이미지를 생성 중이에요 (0/3)", "current": 0, "total": 3},
        {"event": "stage", "track": "text", "status": "done", "label": "광고 문구가 완성됐어요"},
        {"event": "stage", "track": "image", "status": "progress", "label": "이미지를 생성 중이에요 (1/3)", "current": 1, "total": 3},
        {"event": "stage", "track": "image", "status": "progress", "label": "이미지를 생성 중이에요 (2/3)", "current": 2, "total": 3},
        {"event": "stage", "track": "image", "status": "progress", "label": "이미지를 생성 중이에요 (3/3)", "current": 3, "total": 3},
    ]
    if simulate_image_failure:
        stages.append(
            {"event": "stage", "track": "image", "status": "failed", "label": "이미지 생성에 실패했어요"},
        )
    else:
        stages.append(
            {"event": "stage", "track": "image", "status": "done", "label": "이미지가 완성됐어요 (3/3)", "current": 3, "total": 3},
        )
    for stage in stages:
        time.sleep(0.4)
        if on_stage is not None:
            try:
                on_stage(stage)
            except Exception:
                pass

    if simulate_image_failure:
        return {
            "ok": False,
            "error": "이미지 생성에 실패했어요. 잠시 후 다시 시도해 주세요.",
            "error_code": "IMAGE_GENERATION_FAILED",
        }

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