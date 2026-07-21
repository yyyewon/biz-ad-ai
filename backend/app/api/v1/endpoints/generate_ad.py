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
from app.schemas.common import error_response
from app.services.pipelines.generate_pipeline import run_generate_pipeline
from app.utils.upload_image_validator import validate_uploaded_image_bytes


router = APIRouter()


def _should_count_daily_usage(result: dict) -> bool:
    """
    이미지 생성이 실제로 성공한 경우에만 일일 사용량 차감
    """
    return result.get("image_generation_success") is True


def _sse(data: dict[str, Any]) -> str:
    """
    dict를 SSE data: 라인 하나로 직렬화
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _error_event_payload(exc: Exception) -> dict[str, Any]:
    """
    예외를 프론트엔드용 SSE error 이벤트로 변환
    """
    if isinstance(exc, AppException):
        public_detail = None
        if isinstance(exc.detail, dict) and exc.detail.get("request_id"):
            public_detail = {"request_id": exc.detail["request_id"]}

        payload = error_response(
            code=exc.code,
            message=exc.message,
            detail=public_detail,
        )
    else:
        spec = errors.GENERATE_ENDPOINT_FAILED
        payload = error_response(
            code=spec.code,
            message=spec.message,
            detail=None,
        )

    return {
        "event": "error",
        "data": payload,
    }


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
    통합 광고 콘텐츠 생성 API
    """
    image_bytes = None
    if image and image.filename:
        image_bytes = await image.read()
        validate_uploaded_image_bytes(
            image_bytes,
            filename=image.filename,
            content_type=image.content_type,
        )

    if current_user:
        await ensure_daily_quota_available_async(current_user["id"])

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
        "generate_ad_endpoint_started | user_id={} | store_name={} | menu_name={} | has_image={} | food={}",
        current_user["id"] if current_user else None,
        store_name,
        menu_name,
        bool(image_bytes),
        food,
    )

    progress_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    TERMINAL = None

    async def _on_progress(event: dict[str, Any]) -> None:
        await progress_queue.put(event)

    async def _run_pipeline() -> None:
        """
        실제 파이프라인을 실행하고 터미널 이벤트를 큐에 넣는다
        """
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

            usage_count = None
            if current_user and _should_count_daily_usage(result):
                usage_count = await increment_daily_usage_async(current_user["id"])

            logger.info(
                "generate_ad_endpoint_completed | user_id={} | store_name={} | menu_name={} | partial_success={} | usage_count={}",
                current_user["id"] if current_user else None,
                store_name,
                menu_name,
                result.get("partial_success") if isinstance(result, dict) else None,
                usage_count,
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
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
