from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable

from loguru import logger

from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.core.model_config import (
    get_active_profile_name,
    get_model_settings,
)
from app.schemas.food_type import FoodType
from app.schemas.image_ad import ImageAdRequest
from app.services.pipelines.food_type_resolver import require_food_type
from app.services.pipelines.image_pipeline import generate_image_ads
from app.services.pipelines.text_pipeline import run_text_pipeline
from app.utils.image_bytes import encode_image_bytes_to_base64
from app.utils.poster_taglines import resolve_poster_headline
from app.utils.performance_logger import measure_stage, record_performance_metric


def _safe_active_profile_name() -> str:
    """
    active_profile 이름을 안전하게 반환한다.

    성능 로그 기록 중 config 문제가 생기더라도,
    실제 파이프라인 흐름이 깨지지 않도록 unknown으로 처리한다.
    """

    try:
        return get_active_profile_name()
    except Exception:
        return "unknown"


def _safe_model_info(role: str) -> dict[str, str]:
    """
    role별 provider/model 정보를 안전하게 반환한다.

    role options:
    - text_generation
    - image_generation
    """

    try:
        model_info = get_model_settings(role)
        return {
            "provider": str(model_info.get("provider", "unknown")),
            "model": str(model_info.get("model_name", "unknown")),
        }
    except Exception:
        return {
            "provider": "unknown",
            "model": "unknown",
        }

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


async def _emit_progress(
    on_progress: ProgressCallback | None,
    event: dict[str, Any],
) -> None:
    if on_progress is None:
        return
    try:
        await on_progress(event)
    except Exception as exc:
        logger.warning("generate_pipeline_progress_callback_failed | error={}", str(exc))


def _build_image_payload(
    *,
    store_name: str,
    menu_name: str,
    purpose: str,
    food_type: FoodType,
    tone: str,
    image_request: str,
    headline: str | None = None,
    price_text: str | None = None,
    store_location: str | None = None,
) -> ImageAdRequest:
    return ImageAdRequest(
        store_name=store_name,
        menu_name=menu_name,
        store_location=(store_location or "").strip() or None,
        food_type=food_type,
        promotion_goal=purpose,
        tone=tone,
        extra_notes=(image_request or "").strip() or None,
        headline=(headline or "").strip() or None,
        price_text=(price_text or "").strip() or None,
        num_images=3,
        generation_mode="direct_poster",
    )


def _build_image_generation_response(image_result) -> dict[str, Any]:
    """
    이미지 생성 파이프라인 결과 중 프론트/로그에서 확인할 핵심 정보만 정리한다.

    주의:
    - base64 이미지는 최상위 data.images에만 둔다.
    - image_generation 안에는 큰 이미지 데이터를 중복으로 넣지 않는다.
    """

    return {
        "request_id": image_result.request_id,
        "generation_mode": image_result.generation_mode,
        "latency_ms": image_result.latency_ms,
        "stage_latencies_ms": image_result.stage_latencies_ms,
        "num_images": image_result.num_images,
        "poster_image_count": len(image_result.poster_images or []),
        "applied_variants": image_result.applied_variants,
        "food_type": image_result.food_type,
    }


def _record_image_pipeline_stage_metrics(
    *,
    pipeline_request_id: str,
    profile_name: str,
    image_model_info: dict[str, str],
    stage_latencies_ms: dict[str, int],
    image_request_id: str,
) -> None:
    """
    image_pipeline 내부에서 계산된 stage_latencies_ms를 performance.jsonl에 기록한다.
    """

    stage_key_map = {
        "food_generation_ms": "food_generation",
        "poster_generation_ms": "poster_generation",
        "total_ms": "image_pipeline_total",
    }

    for latency_key, stage_name in stage_key_map.items():
        elapsed_ms = stage_latencies_ms.get(latency_key)

        if elapsed_ms is None:
            continue

        record_performance_metric(
            pipeline="ad_generate",
            stage=stage_name,
            request_id=pipeline_request_id,
            profile=profile_name,
            provider=image_model_info["provider"],
            model=image_model_info["model"],
            elapsed_ms=float(elapsed_ms),
            success=True,
            extra={
                "image_request_id": image_request_id,
                "latency_key": latency_key,
            },
        )


def _record_total_pipeline_metric(
    *,
    pipeline_request_id: str,
    profile_name: str,
    total_started: float,
    success: bool,
    partial_success: bool = False,
    error_code: str | None = None,
    error_type: str | None = None,
) -> None:
    """
    통합 파이프라인 전체 소요 시간을 performance.jsonl에 기록한다.
    """

    elapsed_ms = (time.perf_counter() - total_started) * 1000

    record_performance_metric(
        pipeline="ad_generate",
        stage="total_pipeline",
        request_id=pipeline_request_id,
        profile=profile_name,
        provider="mixed",
        model="mixed",
        elapsed_ms=elapsed_ms,
        success=success,
        error_code=error_code,
        error_type=error_type,
        extra={
            "partial_success": partial_success,
        },
    )


async def run_generate_pipeline(
    store_name: str,
    menu_name: str,
    purpose: str,
    food: str,
    llm_request: str,
    image_request: str,
    tone: str,
    price: str = "",
    store_location: str = "",
    image_bytes: bytes | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """
    통합 광고 생성 파이프라인.

    전체 흐름:
    1. 이미지가 있으면 광고 문구 생성과 이미지 생성을 병렬 실행
    2. 이미지가 없으면 광고 문구만 생성
    3. 업로드 이미지 bytes를 image_pipeline에 직접 전달
    4. 광고 이미지 3장 생성
    5. 생성 이미지 base64를 응답에 포함
    """

    pipeline_request_id = f"gen-{uuid.uuid4().hex[:8]}"
    total_started = time.perf_counter()
    profile_name = _safe_active_profile_name()

    logger.info(
        "generate_pipeline_started | request_id={} | profile={} | store_name={} | menu_name={} | has_image={} | food={}",
        pipeline_request_id,
        profile_name,
        store_name,
        menu_name,
        bool(image_bytes),
        food,
    )

    try:
        text_model_info = _safe_model_info("text_generation")

        images: list[str] = []
        image_generation: dict[str, Any] = {}
        warnings: list[dict[str, Any]] = []
        partial_success = False
        image_generation_success: bool | None = None
        image_error_type: str | None = None

        if image_bytes:
            resolved_food_type = require_food_type(food)
            poster_headline = resolve_poster_headline(purpose, tone)
            image_payload = _build_image_payload(
                store_name=store_name,
                menu_name=menu_name,
                purpose=purpose,
                image_request=image_request,
                food_type=resolved_food_type,
                tone=tone,
                headline=poster_headline or None,
                price_text=price,
                store_location=store_location,
            )
            image_model_info = _safe_model_info("image_generation")

            async def _run_text_stage() -> str:
                await _emit_progress(
                    on_progress,
                    {
                        "event": "stage",
                        "track": "text",
                        "status": "start",
                        "label": "광고 문구를 생성 중이에요",
                    },
                )
                try:
                    with measure_stage(
                        pipeline="ad_generate",
                        stage="text_generation",
                        request_id=pipeline_request_id,
                        profile=profile_name,
                        provider=text_model_info["provider"],
                        model=text_model_info["model"],
                        extra={
                            "store_name": store_name,
                            "menu_name": menu_name,
                            "has_image": True,
                            "food_type": resolved_food_type,
                        },
                    ):
                        caption = await run_text_pipeline(
                            store_name=store_name,
                            menu_name=menu_name,
                            purpose=purpose,
                            llm_request=llm_request,
                            tone=tone,
                            food=food,
                            price=price,
                            store_location=store_location,
                        )
                except Exception:
                    await _emit_progress(
                        on_progress,
                        {
                            "event": "stage",
                            "track": "text",
                            "status": "failed",
                            "label": "광고 문구 생성에 실패했어요",
                        },
                    )
                    raise
                else:
                    await _emit_progress(
                        on_progress,
                        {
                            "event": "stage",
                            "track": "text",
                            "status": "done",
                            "label": "광고 문구가 완성됐어요",
                        },
                    )
                    return caption

            text_task = asyncio.create_task(_run_text_stage())

            try:
                await _emit_progress(
                    on_progress,
                    {
                        "event": "stage",
                        "track": "image",
                        "status": "start",
                        "label": "이미지를 생성 중이에요 (0/{})".format(image_payload.num_images),
                        "current": 0,
                        "total": image_payload.num_images,
                    },
                )

                async def _on_variant_done(done_count: int, total: int) -> None:
                    await _emit_progress(
                        on_progress,
                        {
                            "event": "stage",
                            "track": "image",
                            "status": "progress",
                            "label": "이미지를 생성 중이에요 ({}/{})".format(done_count, total),
                            "current": done_count,
                            "total": total,
                        },
                    )

                with measure_stage(
                    pipeline="ad_generate",
                    stage="image_generation",
                    request_id=pipeline_request_id,
                    profile=profile_name,
                    provider=image_model_info["provider"],
                    model=image_model_info["model"],
                    extra={
                        "num_images": image_payload.num_images,
                        "generation_mode": image_payload.generation_mode,
                    },
                ):
                    image_result = await generate_image_ads(
                        payload=image_payload,
                        source_image_bytes=image_bytes,
                        on_variant_done=_on_variant_done,
                    )

                _record_image_pipeline_stage_metrics(
                    pipeline_request_id=pipeline_request_id,
                    profile_name=profile_name,
                    image_model_info=image_model_info,
                    stage_latencies_ms=image_result.stage_latencies_ms or {},
                    image_request_id=image_result.request_id,
                )

                images = list(image_result.images or [])

                if not images and image_result.image_bytes_list:
                    images = [
                        encode_image_bytes_to_base64(image_data)
                        for image_data in image_result.image_bytes_list
                    ]

                if not images:
                    raise AppException(
                        errors.IMAGE_GENERATION_EMPTY_RESULT,
                        detail={
                            "stage": "poster_generation",
                            "request_id": pipeline_request_id,
                        },
                    )

                while len(images) < 3:
                    images.append(images[-1])

                image_generation = _build_image_generation_response(image_result)
                image_generation_success = True

                await _emit_progress(
                    on_progress,
                    {
                        "event": "stage",
                        "track": "image",
                        "status": "done",
                        "label": "이미지가 완성됐어요 ({0}/{0})".format(image_payload.num_images),
                        "current": image_payload.num_images,
                        "total": image_payload.num_images,
                    },
                )

            except asyncio.CancelledError:
                if not text_task.done():
                    text_task.cancel()
                await asyncio.gather(text_task, return_exceptions=True)
                raise

            except Exception as exc:
                logger.exception(
                    "image_generation_failed_in_generate_pipeline | request_id={} | error={}",
                    pipeline_request_id,
                    str(exc),
                )

                images = []

                partial_success = True
                image_generation_success = False
                image_error_type = exc.__class__.__name__

                error_code = exc.code if isinstance(exc, AppException) else "UNHANDLED_EXCEPTION"

                warnings.append(
                    {
                        "code": error_code,
                        "message": "이미지 생성에 실패했어요. 잠시 후 다시 시도해 주세요.",
                        "detail": {
                            "request_id": pipeline_request_id,
                        },
                    }
                )

                await _emit_progress(
                    on_progress,
                    {
                        "event": "stage",
                        "track": "image",
                        "status": "failed",
                        "label": "이미지 생성에 실패했어요",
                    },
                )

            try:
                caption = await text_task
            except asyncio.CancelledError:
                if not text_task.done():
                    text_task.cancel()
                await asyncio.gather(text_task, return_exceptions=True)
                raise
        else:
            await _emit_progress(
                on_progress,
                {
                    "event": "stage",
                    "track": "text",
                    "status": "start",
                    "label": "광고 문구를 생성 중이에요",
                },
            )
            try:
                with measure_stage(
                    pipeline="ad_generate",
                    stage="text_generation",
                    request_id=pipeline_request_id,
                    profile=profile_name,
                    provider=text_model_info["provider"],
                    model=text_model_info["model"],
                    extra={
                        "store_name": store_name,
                        "menu_name": menu_name,
                        "has_image": False,
                    },
                ):
                    caption = await run_text_pipeline(
                        store_name=store_name,
                        menu_name=menu_name,
                        purpose=purpose,
                        llm_request=llm_request,
                        tone=tone,
                        food=food,
                        price=price,
                        store_location=store_location,
                    )
            except Exception:
                await _emit_progress(
                    on_progress,
                    {
                        "event": "stage",
                        "track": "text",
                        "status": "failed",
                        "label": "광고 문구 생성에 실패했어요",
                    },
                )
                raise
            else:
                await _emit_progress(
                    on_progress,
                    {
                        "event": "stage",
                        "track": "text",
                        "status": "done",
                        "label": "광고 문구가 완성됐어요",
                    },
                )

        response: dict[str, Any] = {
            "caption": caption,
            "images": images,
            "partial_success": partial_success,
            "warnings": warnings,
            "image_generation_success": image_generation_success,
        }

        if image_generation:
            response["image_generation"] = image_generation

        if warnings:
            response["image_generation_error"] = warnings[0]["message"]

        total_success = not partial_success
        total_error_code = warnings[0]["code"] if warnings else None
        total_error_type = image_error_type if warnings else None

        _record_total_pipeline_metric(
            pipeline_request_id=pipeline_request_id,
            profile_name=profile_name,
            total_started=total_started,
            success=total_success,
            partial_success=partial_success,
            error_code=total_error_code,
            error_type=total_error_type,
        )

        logger.info(
            "generate_pipeline_completed | request_id={} | partial_success={} | image_generation_success={}",
            pipeline_request_id,
            partial_success,
            image_generation_success,
        )

        return response

    except AppException as exc:
        _record_total_pipeline_metric(
            pipeline_request_id=pipeline_request_id,
            profile_name=profile_name,
            total_started=total_started,
            success=False,
            partial_success=False,
            error_code=exc.code,
            error_type=exc.__class__.__name__,
        )
        raise

    except Exception as exc:
        logger.exception(
            "generate_pipeline_failed | request_id={} | error={}",
            pipeline_request_id,
            str(exc),
        )

        _record_total_pipeline_metric(
            pipeline_request_id=pipeline_request_id,
            profile_name=profile_name,
            total_started=total_started,
            success=False,
            partial_success=False,
            error_code="UNHANDLED_EXCEPTION",
            error_type=exc.__class__.__name__,
        )

        error_spec = getattr(errors, "GENERATE_PIPELINE_IMAGE_FAILED", errors.IMAGE_PIPELINE_FAILED)

        raise AppException(
            error_spec,
            detail={
                "request_id": pipeline_request_id,
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        ) from exc
