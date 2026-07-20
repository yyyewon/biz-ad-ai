from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger

from app.core import error_constants as errors
from app.core.concurrency import generation_limiter
from app.core.deps import get_current_user_optional
from app.core.exceptions import AppException
from app.core.quota import ensure_daily_quota_available_async, increment_daily_usage_async
from app.core.user_repository import update_user_business_info
from app.services.pipelines.generate_pipeline import run_generate_pipeline
from app.utils.upload_image_validator import validate_uploaded_image_bytes


router = APIRouter()


def _should_count_daily_usage(result: dict) -> bool:
    """이미지 생성이 실제로 성공한 경우에만 일일 사용량을 차감한다."""
    return result.get("image_generation_success") is True


def _sse(data: dict[str, Any]) -> str:
    """dict를 SSE data: 라인 하나로 직렬화한다."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _error_event_payload(exc: Exception) -> dict[str, Any]:
    """예외를 프론트엔드용 SSE error 이벤트로 변환한다."""
    if isinstance(exc, AppException):
        return {
            "event": "error",
            "code": exc.code,
            "message": exc.message,
            "detail": exc.detail,
        }
    return {
        "event": "error",
        "code": "GENERATE_ENDPOINT_FAILED",
        "message": "광고 생성 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.",
        "detail": {
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        },
    }


def _single_event_streaming_response(event: dict[str, Any]) -> StreamingResponse:
    """하나의 이벤트만 보내고 닫는 SSE 응답(사전 검증 실패 등)."""

    async def _stream() -> AsyncIterator[str]:
        yield _sse(event)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/generate")
async def generate_ad_endpoint(
    store_name: str = Form(..., description="가게 이름"),
    menu_name: str = Form(..., description="메뉴 이름"),
    purpose: str | None = Form(None, description="광고 목적"),
    food: str = Form("", description="음식 종류"),
    tone: str = Form("", description="톤앤매너"),
    price: str = Form("", description="메뉴 가격"),
    store_location: str = Form("", description="가게 위치/지역"),
    image_request: str = Form("", description="이미지 생성 요구사항"),
    llm_request: str = Form("", description="광고 문구 생성 요구사항"),
    image: UploadFile | None = File(None, description="참고용 이미지"),
    current_user: dict | None = Depends(get_current_user_optional),
):
    """
    통합 광고 콘텐츠 생성 API (SSE 스트리밍).

    응답은 text/event-stream으로 흘러가며, 각 이벤트는 한 줄 JSON이다.
    - stage 이벤트: text/image 트랙의 시작·진행·완료/실패 상태
    - result 이벤트: 최종 생성 결과(caption, images, ...)
    - error 이벤트: 파이프라인/엔드포인트 오류
    """
    # 업로드된 이미지 파일 읽기
    image_bytes = None
    if image and image.filename:
        image_bytes = await image.read()
        try:
            validate_uploaded_image_bytes(
                image_bytes,
                filename=image.filename,
                content_type=image.content_type,
            )
        except AppException as exc:
            # exc를 즉시 payload로 변환: 중첩 클로저의 free variable 캡처 이슈를 피한다.
            validation_payload = _error_event_payload(exc)
            return _single_event_streaming_response(validation_payload)

    # 로그인된 사용자: 한도 확인만 먼저 (실패 시에는 차감하지 않음)
    if current_user:
        try:
            await ensure_daily_quota_available_async(current_user["id"])
        except AppException as exc:
            quota_payload = _error_event_payload(exc)
            return _single_event_streaming_response(quota_payload)

        # 생성 결과와 무관하게, 유효한 이미지 생성 요청이 접수된 시점의 최신
        # 가게 정보를 저장한다. 파이프라인 실패/클라이언트 연결 종료가 발생해도
        # 다음 Step 1 진입 시 이번 요청 값을 불러올 수 있어야 한다.
        update_user_business_info(
            user_id=current_user["id"],
            store_name=store_name,
            store_location=store_location,
        )
        logger.info(
            "generate_ad_business_info_updated | user_id={} | store_name={} | store_location={}",
            current_user["id"],
            store_name.strip(),
            store_location.strip(),
        )

    logger.info(
        "generate_ad_endpoint_started | store_name={} | menu_name={} | has_image={} | food={}",
        store_name,
        menu_name,
        bool(image_bytes),
        food,
    )

    # 파이프라인 진행 상황 이벤트를 SSE로 내보내기 위한 큐.
    # 터미널 이벤트(result/error)가 들어오면 스트림을 종료한다.
    progress_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    TERMINAL = None

    async def _on_progress(event: dict[str, Any]) -> None:
        await progress_queue.put(event)

    async def _run_pipeline() -> None:
        """실제 파이프라인을 실행하고 터미널 이벤트를 큐에 넣는다."""
        try:
            async with generation_limiter.slot():
                result = await run_generate_pipeline(
                    store_name=store_name,
                    menu_name=menu_name,
                    purpose=purpose or "홍보",
                    food=food,
                    tone=tone,
                    price=price,
                    store_location=store_location,
                    image_request=image_request,
                    llm_request=llm_request,
                    image_bytes=image_bytes,
                    on_progress=_on_progress,
                )

            # 이미지 생성이 성공한 로그인 사용자: 일일 사용량 차감
            if current_user and _should_count_daily_usage(result):
                await increment_daily_usage_async(current_user["id"])

            logger.info(
                "generate_ad_endpoint_completed | store_name={} | menu_name={} | partial_success={}",
                store_name,
                menu_name,
                result.get("partial_success") if isinstance(result, dict) else None,
            )

            await progress_queue.put({"event": "result", "data": result})

        except AppException as exc:
            logger.warning(
                "generate_ad_endpoint_pipeline_failed | store_name={} | code={} | error={}",
                store_name,
                exc.code,
                str(exc),
            )
            await progress_queue.put(_error_event_payload(exc))

        except Exception as exc:
            logger.exception(
                "generate_ad_endpoint_failed | store_name={} | menu_name={} | error={}",
                store_name,
                menu_name,
                str(exc),
            )
            await progress_queue.put(_error_event_payload(exc))

        finally:
            await progress_queue.put(TERMINAL)

    async def _event_stream() -> AsyncIterator[str]:
        pipeline_task = asyncio.create_task(_run_pipeline())
        try:
            while True:
                event = await progress_queue.get()
                if event is TERMINAL:
                    break
                yield _sse(event)
        finally:
            if not pipeline_task.done():
                pipeline_task.cancel()
                try:
                    await pipeline_task
                except Exception:
                    pass

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx 프록시 버퍼링 방지
        },
    )
