from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from loguru import logger
from starlette.concurrency import run_in_threadpool

from app.api.v1.endpoints.image_preprocess import run_remove_background_and_resize
from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.core.model_config import (
    get_active_profile_name,
    get_image_preprocess_settings,
    get_model_settings,
)
from app.schemas.image_ad import ImageAdRequest
from app.services.pipelines.image_pipeline import generate_image_ads
from app.services.pipelines.text_pipeline import run_text_pipeline
from app.utils.image_bytes import encode_image_bytes_to_base64
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


def _safe_image_preprocess_info() -> dict[str, str]:
    """
    image_preprocess provider 정보를 안전하게 반환한다.
    """

    try:
        settings = get_image_preprocess_settings()
        provider = str(settings.get("provider", "rembg"))
        return {
            "provider": provider,
            "model": provider,
        }
    except Exception:
        return {
            "provider": "rembg",
            "model": "rembg",
        }


def _build_image_payload(
    *,
    store_name: str,
    menu_name: str,
    purpose: str,
    food: str,
    tone: str,
    image_request: str,
) -> ImageAdRequest:
    normalized_mood, normalized_mood_list = _normalize_image_moods(moods or [])

    return ImageAdRequest(
        store_name=store_name,
        menu_name=menu_name,
        promotion_goal=purpose,
        tone=tone,
        image_request=image_request,
        food=food,
        num_images=3,
        generation_mode="two_stage",
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

    image_pipeline.py가 이미 계산하는 값을 재사용해서
    PPT/보고서용 분석 로그로 남긴다.
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
    image_bytes: bytes | None = None,
) -> dict[str, Any]:
    """
    통합 광고 생성 파이프라인.

    전체 흐름:
    1. 이미지가 있으면 광고 문구 생성 + 이미지 전처리를 병렬 실행
    2. 이미지가 없으면 광고 문구만 생성
    3. 전처리된 이미지 bytes를 image_pipeline에 직접 전달
    4. 광고 이미지 3장을 병렬 생성
    5. 생성 이미지 base64를 응답에 포함
    6. 텍스트 + 이미지 결과를 통합 응답으로 반환
    7. 단계별/전체 소요 시간을 performance.jsonl에 기록
    이미지 생성 실패 시:
    - 광고 문구는 유지한다.
    - fallback 이미지를 반환한다.
    - partial_success=true로 표시한다.
    - warnings에 실패 원인을 남긴다.
    - image_generation_success=false로 표시한다.
    """

    pipeline_request_id = f"gen-{uuid.uuid4().hex[:8]}"
    total_started = time.perf_counter()
    profile_name = _safe_active_profile_name()

    logger.info(
        "generate_pipeline_started | request_id={} | profile={} | store_name={} | menu_name={} | has_image={}",
        pipeline_request_id,
        profile_name,
        store_name,
        menu_name,
        bool(image_bytes),
    )

    try:
        text_model_info = _safe_model_info("text_generation")

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
                "has_image": bool(image_bytes),
            },
        ):
            caption = run_text_pipeline(
                store_name=store_name,
                menu_name=menu_name,
                purpose=purpose,
                llm_request=llm_request,
                tone=tone,
            )

        # ========================================================
        # 2. 응답 기본값 초기화
        # ========================================================
        images: list[str] = []
        image_generation: dict[str, Any] = {}
        warnings: list[dict[str, Any]] = []
        partial_success = False
        image_generation_success: bool | None = None
        processed_bytes: bytes | None = None

        if image_bytes:
            preprocess_info = _safe_image_preprocess_info()

            async def _run_text_stage() -> str:
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
                    },
                ):
                    return await run_text_pipeline(
                        store_name=store_name,
                        menu_name=menu_name,
                        purpose=purpose,
                        llm_request=llm_request,
                        tone=tone,
                    )

            async def _run_preprocess_stage() -> bytes:
                with measure_stage(
                    pipeline="ad_generate",
                    stage="image_preprocess",
                    request_id=pipeline_request_id,
                    profile=profile_name,
                    provider=preprocess_info["provider"],
                    model=preprocess_info["model"],
                    extra={
                        "input_bytes": len(image_bytes),
                    },
                ):
                    result = await run_in_threadpool(
                        run_remove_background_and_resize,
                        image_bytes,
                    )

                if not result:
                    raise AppException(
                        errors.IMAGE_GENERATION_EMPTY_RESULT,
                        detail={
                            "stage": "image_preprocess",
                            "request_id": pipeline_request_id,
                        },
                    )

                return result

            caption, processed_bytes = await asyncio.gather(
                _run_text_stage(),
                _run_preprocess_stage(),
            )

            try:
                image_payload = _build_image_payload(
                    store_name=store_name,
                    menu_name=menu_name,
                    purpose=purpose,
                    image_request=image_request,
                    food=food,
                    tone=tone,
                )

                image_model_info = _safe_model_info("image_generation")

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
                        original_image_bytes=image_bytes,
                        subject_cutout_bytes=processed_bytes,
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

            except Exception as exc:
                logger.exception(
                    "image_generation_failed_in_generate_pipeline | request_id={} | error={}",
                    pipeline_request_id,
                    str(exc),
                )

                fallback_bytes = processed_bytes or image_bytes
                fallback_b64 = encode_image_bytes_to_base64(fallback_bytes)
                images = [fallback_b64, fallback_b64, fallback_b64]

                partial_success = True
                image_generation_success = False

                error_code = exc.code if isinstance(exc, AppException) else "UNHANDLED_EXCEPTION"

                warnings.append(
                    {
                        "code": error_code,
                        "message": "포스터 생성 실패로 fallback 이미지를 반환했습니다.",
                        "detail": {
                            "request_id": pipeline_request_id,
                            "error_type": exc.__class__.__name__,
                            "error": str(exc),
                        },
                    }
                )
        else:
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

        # ========================================================
        # 5. 통합 파이프라인 전체 소요 시간 기록
        # ========================================================
        total_success = not partial_success
        total_error_code = warnings[0]["code"] if warnings else None
        total_error_type = warnings[0]["detail"]["error_type"] if warnings else None

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
