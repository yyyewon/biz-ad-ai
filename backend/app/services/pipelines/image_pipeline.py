from __future__ import annotations

import asyncio
import time
import uuid
from typing import Awaitable, Callable, Optional

from loguru import logger
from PIL import Image

from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.schemas.image_ad import (
    DEFAULT_IMAGE_VARIANTS,
    ImageAdRequest,
    ImageAdResponse,
    ImageVariantType,
)
from app.core.model_config import get_provider_name, get_variant_image_size, get_model_settings
from app.schemas.performance_metrics import MetricId
from app.services.pipelines.image_variant_prompts import (
    SDXLPrompt,
    build_hf_variant_prompts,
    build_variant_prompt,
    resolve_variant_render_mode,
)
from app.services.providers.base import ImageRenderMode
from app.services.providers.factory import get_image_provider
from app.utils.food_subject import PreparedFoodSubject, prepare_food_subject
from app.utils.image_processor import shrink_and_pad_for_wider_framing, zoom_center_crop
from app.utils.image_bytes import (
    encode_image_bytes_to_base64,
    image_bytes_to_pil,
    pil_image_to_png_bytes,
)
from app.utils.image_text_overlay import (
    apply_variant_text_overlay,
    variant_uses_pil_text_overlay,
)
from app.utils.performance_logger import record_registry_metric
from app.utils.variant_compositor import (
    PreparedVariantInput,
    evaluate_poster_background,
    prepare_variant_input,
    recomposite_subject,
)


def _safe_image_model_info(provider_name: str) -> dict[str, str]:
    try:
        model_info = get_model_settings("image_generation", provider_name=provider_name)
        return {
            "provider": str(model_info.get("provider", provider_name)),
            "model": str(model_info.get("model_name", "unknown")),
        }
    except Exception:
        return {"provider": provider_name, "model": "unknown"}


def _prepare_edit_source_bytes(
    source_bytes: bytes,
    *,
    food_type: str | None,
    variant: ImageVariantType,
) -> bytes:
    """
    provider 입력용 소스 이미지를 준비한다.

    - studio: 축소·패딩으로 미디엄 와이드 구도 유도
    - instagram_feed: 중앙 줌으로 릴스용 음식 클로즈업 유도
    """

    image = image_bytes_to_pil(source_bytes).convert("RGB")

    if food_type:
        if variant == "studio":
            image = shrink_and_pad_for_wider_framing(image)
        elif variant == "instagram_feed":
            image = zoom_center_crop(image, zoom_factor=1.28)

        logger.info(
            "image_edit_source_reframed | food_type={} | variant={} | size={}",
            food_type,
            variant,
            image.size,
        )

    return pil_image_to_png_bytes(image)


POSTER_EMPTY_RESULT_RETRY_SUFFIXES: list[str] = [
    "",
    "retry: zero text in image, no menu title, no price, no store label, no STORE/NAME words, food+bg only",
    "final retry: completely blank text zones, no Korean or English letters or numbers in image pixels",
]


def _resolve_image_variant(index: int) -> ImageVariantType:
    return DEFAULT_IMAGE_VARIANTS[index % len(DEFAULT_IMAGE_VARIANTS)]


async def _generate_poster_with_retries(
    *,
    provider,
    source_image_bytes: bytes,
    base_prompt: str,
    request_id: str,
    variant: ImageVariantType,
    mask_image_bytes: bytes | None = None,
    size: str | None = None,
    render_mode: ImageRenderMode = "photo_restyle",
    negative_prompt: str | None = None,
    img2img_strength: float | None = None,
    reference_image_bytes: bytes | None = None,
    ip_adapter_scale: float | None = None,
    prompt_2: str | None = None,
    seed: int | None = None,
    num_inference_steps: int | None = None,
    guidance_scale: float | None = None,
    inpaint_strength: float | None = None,
    variant_strategy: str | None = None,
) -> list[bytes]:
    attempt_max = len(POSTER_EMPTY_RESULT_RETRY_SUFFIXES)

    for attempt_idx, suffix in enumerate(POSTER_EMPTY_RESULT_RETRY_SUFFIXES):
        attempt = attempt_idx + 1
        retry_prompt = f"{base_prompt}, {suffix}" if suffix else base_prompt

        generate_kwargs = {
            "input_image_bytes": source_image_bytes,
            "mask_image_bytes": mask_image_bytes,
            "prompt": retry_prompt,
            "num_images": 1,
            "size": size,
            "render_mode": render_mode,
        }
        if negative_prompt is not None:
            generate_kwargs["negative_prompt"] = negative_prompt
        if img2img_strength is not None:
            generate_kwargs["img2img_strength"] = img2img_strength
        if reference_image_bytes is not None:
            generate_kwargs.update(
                {
                    "reference_image_bytes": reference_image_bytes,
                    "ip_adapter_scale": ip_adapter_scale,
                    "prompt_2": prompt_2,
                    "seed": seed,
                    "num_inference_steps": num_inference_steps,
                    "guidance_scale": guidance_scale,
                    "inpaint_strength": inpaint_strength,
                    "variant": variant,
                    "variant_strategy": variant_strategy,
                }
            )

        image_bytes_list = await provider.generate(**generate_kwargs)

        if image_bytes_list:
            record_registry_metric(
                MetricId.EMPTY_RESULT_RETRY_ATTEMPT,
                request_id=request_id,
                success=True,
                extra={
                    "variant": variant,
                    "attempt": attempt,
                    "attempt_max": attempt_max,
                    "render_mode": render_mode,
                },
            )
            return image_bytes_list

        logger.warning(
            "poster_generation_empty_result | attempt={} | render_mode={}",
            attempt,
            render_mode,
        )
        record_registry_metric(
            MetricId.EMPTY_RESULT_RETRY_ATTEMPT,
            request_id=request_id,
            success=False,
            extra={
                "variant": variant,
                "attempt": attempt,
                "attempt_max": attempt_max,
                "render_mode": render_mode,
            },
        )

    raise AppException(
        errors.IMAGE_POSTER_RETRY_FAILED,
        detail={
            "attempt_count": attempt_max,
            "reason": "empty_result",
        },
    )


async def generate_image_ads(
    payload: ImageAdRequest,
    source_image_bytes: bytes,
    seed: Optional[int] = None,
    on_variant_done: Callable[[int, int], Awaitable[None]] | None = None,
    metrics_request_id: str | None = None,
) -> ImageAdResponse:
    """
    이미지 광고 생성 파이프라인.

    메모리 기반 처리 기준:
    - 입력 이미지는 bytes로 받는다.
    - 전처리 source/mask/poster 이미지를 서버 디스크에 저장하지 않는다.
    - provider는 list[bytes]를 반환한다.
    - API 응답용 이미지는 base64 문자열로 변환한다.
    - 포스터/스튜디오/인스타피드 유형별로 num_images 개수만큼 병렬 실행한다.

    on_variant_done:
        각 variant 생성이 완료될 때마다 (done_count, total) 로 호출되는 비동기 콜백.
        프론트엔드 진행률 표시(SSE)용이며, None이면 호출하지 않는다.
    """

    started = time.perf_counter()
    request_id = f"img-{uuid.uuid4().hex[:10]}"
    trace_request_id = metrics_request_id or request_id

    if not source_image_bytes:
        raise AppException(
            errors.EMPTY_IMAGE_FILE,
            detail={"request_id": request_id},
        )

    if not payload.food_type:
        raise AppException(
            errors.MISSING_FOOD_TYPE,
            detail={"request_id": request_id, "stage": "image_pipeline"},
        )

    logger.info(
        "image_pipeline_started | request_id={} | num_images={} | food_type={} | input_bytes={}",
        request_id,
        payload.num_images,
        payload.food_type,
        len(source_image_bytes),
    )

    try:
        source_rgb = image_bytes_to_pil(source_image_bytes).convert("RGB")
        prepared_source_bytes = pil_image_to_png_bytes(source_rgb)

        provider = get_image_provider()
        image_provider_name = get_provider_name("image_generation")
        image_model_info = _safe_image_model_info(image_provider_name)
        hf_variant_settings: dict[str, dict[str, object]] = {}
        prepared_subject: PreparedFoodSubject | None = None
        if image_provider_name == "hf":
            hf_settings = get_model_settings(
                role="image_generation",
                provider_name="hf",
            )["settings"]
            configured_variants = hf_settings.get("variants", {})
            if isinstance(configured_variants, dict):
                hf_variant_settings = {
                    str(key): value
                    for key, value in configured_variants.items()
                    if isinstance(value, dict)
                }
            prepared_subject = await asyncio.to_thread(
                prepare_food_subject,
                source_rgb,
            )

        prompt_used = ""
        stage_latencies_ms: dict[str, int] = {}

        poster_stage_started = time.perf_counter()

        async def _generate_variant_image(
            idx: int,
        ) -> tuple[int, ImageVariantType, bytes, str, int, int | None]:
            variant = _resolve_image_variant(idx)
            variant_size = get_variant_image_size(variant)
            prepared_variant: PreparedVariantInput | None = None
            sdxl_prompt: SDXLPrompt | None = None
            background_fallback_used = False

            if image_provider_name == "hf" and prepared_subject is not None:
                sdxl_prompt = build_hf_variant_prompts(
                    payload,
                    variant,
                    food_type=payload.food_type,
                )
                variant_prompt = sdxl_prompt.prompt
                negative_prompt = sdxl_prompt.negative_prompt
                prepared_variant = await asyncio.to_thread(
                    prepare_variant_input,
                    prepared_subject,
                    variant,
                    food_type=payload.food_type,
                    settings=hf_variant_settings.get(variant),
                )
                edit_source_bytes = prepared_variant.init_image_bytes
                render_mode = prepared_variant.render_mode
                img2img_strength = prepared_variant.img2img_strength
                variant_strategy = (
                    "subject_inpaint"
                    if render_mode == "background_swap"
                    else (
                        "scene_img2img"
                        if variant == "instagram_feed"
                        else "segmentation_img2img_fallback"
                    )
                )
            else:
                variant_prompt = build_variant_prompt(
                    payload,
                    variant,
                    food_type=payload.food_type,
                )
                negative_prompt = None
                edit_source_bytes = _prepare_edit_source_bytes(
                    prepared_source_bytes,
                    food_type=payload.food_type,
                    variant=variant,
                )
                render_mode = resolve_variant_render_mode(
                    variant,
                    image_provider=image_provider_name,
                )
                img2img_strength = None
                variant_strategy = "openai_photo_restyle"

            pipeline_kind = (
                "inpaint" if render_mode == "background_swap" else "img2img"
            )
            metric_extra = {
                "variant": variant,
                "variant_strategy": variant_strategy,
                "pipeline_kind": pipeline_kind,
                "render_mode": render_mode,
                "provider": image_provider_name,
                "image_request_id": request_id,
                "final_size": variant_size,
                "segmentation_valid": (
                    prepared_variant.segmentation_valid if prepared_variant else None
                ),
                "segmentation_fallback_reason": (
                    prepared_variant.segmentation_fallback_reason
                    if prepared_variant
                    else None
                ),
                "native_size": (
                    f"{prepared_variant.native_size[0]}x{prepared_variant.native_size[1]}"
                    if prepared_variant
                    else None
                ),
                "img2img_strength": img2img_strength,
                "inpaint_strength": (
                    prepared_variant.inpaint_strength if prepared_variant else None
                ),
                "ip_adapter_scale": (
                    prepared_variant.ip_adapter_scale if prepared_variant else None
                ),
                "subject_bbox": (
                    prepared_variant.subject_bbox if prepared_variant else None
                ),
                "subject_area_ratio": (
                    prepared_variant.subject_area_ratio if prepared_variant else None
                ),
                "text_safe_zone_ratio": (
                    prepared_variant.text_safe_zone_ratio if prepared_variant else None
                ),
            }

            logger.info(
                "image_variant_generation_started | variant={} | provider={} | render_mode={} | img2img_strength={}",
                variant,
                image_provider_name,
                render_mode,
                img2img_strength,
            )

            variant_started = time.perf_counter()
            try:
                variant_outputs = await _generate_poster_with_retries(
                    provider=provider,
                    source_image_bytes=edit_source_bytes,
                    base_prompt=variant_prompt,
                    request_id=trace_request_id,
                    variant=variant,
                    size=variant_size,
                    render_mode=render_mode,
                    negative_prompt=negative_prompt,
                    img2img_strength=img2img_strength,
                    mask_image_bytes=(
                        prepared_variant.mask_image_bytes if prepared_variant else None
                    ),
                    reference_image_bytes=(
                        prepared_variant.reference_image_bytes if prepared_variant else None
                    ),
                    ip_adapter_scale=(
                        prepared_variant.ip_adapter_scale if prepared_variant else None
                    ),
                    prompt_2=sdxl_prompt.prompt_2 if sdxl_prompt else None,
                    seed=(seed if seed is not None else payload.seed),
                    num_inference_steps=(
                        prepared_variant.num_inference_steps if prepared_variant else None
                    ),
                    guidance_scale=(
                        prepared_variant.guidance_scale if prepared_variant else None
                    ),
                    inpaint_strength=(
                        prepared_variant.inpaint_strength if prepared_variant else None
                    ),
                    variant_strategy=variant_strategy,
                )
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - variant_started) * 1000
                if (
                    prepared_variant is not None
                    and prepared_variant.background_fallback_bytes is not None
                    and render_mode == "background_swap"
                ):
                    background_fallback_used = True
                    variant_outputs = [prepared_variant.background_fallback_bytes]
                    logger.warning(
                        "image_variant_inpaint_fallback | variant={} | error_type={} | error={}",
                        variant,
                        exc.__class__.__name__,
                        str(exc),
                    )
                else:
                    error_code = (
                        exc.code
                        if isinstance(exc, AppException)
                        else "UNHANDLED_EXCEPTION"
                    )
                    record_registry_metric(
                        MetricId.VARIANT_GENERATION_LATENCY,
                        request_id=trace_request_id,
                        elapsed_ms=elapsed_ms,
                        success=False,
                        provider=image_model_info["provider"],
                        model=image_model_info["model"],
                        error_code=error_code,
                        error_type=exc.__class__.__name__,
                        extra={**metric_extra, "background_fallback_used": False},
                    )
                    raise
            provider_latency_ms = int(
                (time.perf_counter() - variant_started) * 1000
            )

            if not variant_outputs:
                raise AppException(
                    errors.IMAGE_GENERATION_EMPTY_RESULT,
                    detail={
                        "request_id": request_id,
                        "stage": "poster_generation",
                        "index": idx,
                        "variant": variant,
                    },
                )

            poster_bytes = variant_outputs[0]
            overlay_latency_ms: int | None = None

            if prepared_variant is not None:
                generated_image = image_bytes_to_pil(poster_bytes).convert("RGB")
                final_width, final_height = (
                    int(value) for value in variant_size.lower().split("x", maxsplit=1)
                )
                if generated_image.size != (final_width, final_height):
                    generated_image = generated_image.resize(
                        (final_width, final_height),
                        Image.Resampling.LANCZOS,
                    )

                if variant == "poster" and not background_fallback_used:
                    quality = evaluate_poster_background(generated_image)
                    logger.info(
                        "poster_background_quality | accepted={} | edge_mean={:.3f} | luminance_variance={:.3f}",
                        quality.accepted,
                        quality.edge_mean,
                        quality.luminance_variance,
                    )
                    if (
                        not quality.accepted
                        and prepared_variant.background_fallback_bytes is not None
                    ):
                        background_fallback_used = True
                        generated_image = image_bytes_to_pil(
                            prepared_variant.background_fallback_bytes
                        ).convert("RGB").resize(
                            (final_width, final_height),
                            Image.Resampling.LANCZOS,
                        )

                if prepared_variant.subject_layer_bytes is not None:
                    subject_layer = image_bytes_to_pil(
                        prepared_variant.subject_layer_bytes
                    ).convert("RGBA")
                    generated_image = recomposite_subject(
                        generated_image,
                        subject_layer,
                    )
                poster_bytes = pil_image_to_png_bytes(generated_image)

            elapsed_ms = (time.perf_counter() - variant_started) * 1000
            record_registry_metric(
                MetricId.VARIANT_GENERATION_LATENCY,
                request_id=trace_request_id,
                elapsed_ms=elapsed_ms,
                success=True,
                provider=image_model_info["provider"],
                model=image_model_info["model"],
                extra={
                    **metric_extra,
                    "background_fallback_used": background_fallback_used,
                },
            )

            if variant_uses_pil_text_overlay(payload.food_type, variant):
                overlay_started = time.perf_counter()
                poster_bytes = await asyncio.to_thread(
                    apply_variant_text_overlay,
                    poster_bytes,
                    payload=payload,
                    variant=variant,
                )
                overlay_latency_ms = int(
                    (time.perf_counter() - overlay_started) * 1000
                )
                logger.info(
                    "image_text_overlay_applied | variant={} | food_type={} | latency_ms={}",
                    variant,
                    payload.food_type,
                    overlay_latency_ms,
                )

            return (
                idx,
                variant,
                poster_bytes,
                variant_prompt,
                provider_latency_ms,
                overlay_latency_ms,
            )

        variant_results: list[
            tuple[int, ImageVariantType, bytes, str, int, int | None]
        ] = []

        async def _notify_progress() -> None:
            if on_variant_done is None:
                return
            try:
                await on_variant_done(len(variant_results), payload.num_images)
            except Exception as exc:
                logger.warning(
                    "image_variant_progress_callback_failed | error={}",
                    str(exc),
                )

        if image_provider_name == "hf":
            execution_indices = sorted(
                range(payload.num_images),
                key=lambda index: (
                    1 if _resolve_image_variant(index) == "instagram_feed" else 0,
                    index,
                ),
            )
            for idx in execution_indices:
                variant_results.append(await _generate_variant_image(idx))
                await _notify_progress()
        else:
            tasks = [
                asyncio.create_task(_generate_variant_image(idx))
                for idx in range(payload.num_images)
            ]
            try:
                for completed in asyncio.as_completed(tasks):
                    variant_results.append(await completed)
                    await _notify_progress()
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        variant_results.sort(key=lambda item: item[0])

        poster_image_bytes: list[bytes] = []
        applied_variants: list[ImageVariantType] = []
        variant_prompts: dict[str, str] = {}
        provider_latencies_ms: list[int] = []
        overlay_latencies_ms: list[int] = []
        for (
            idx,
            variant,
            poster_bytes,
            variant_prompt,
            provider_latency_ms,
            overlay_latency_ms,
        ) in variant_results:
            poster_image_bytes.append(poster_bytes)
            applied_variants.append(variant)
            variant_prompts[variant] = variant_prompt
            provider_latencies_ms.append(provider_latency_ms)
            if overlay_latency_ms is not None:
                overlay_latencies_ms.append(overlay_latency_ms)

            if not prompt_used:
                prompt_used = variant_prompt

        stage_latencies_ms["poster_generation_ms"] = int(
            (time.perf_counter() - poster_stage_started) * 1000
        )
        if provider_latencies_ms:
            stage_latencies_ms["provider_generation_max_ms"] = max(
                provider_latencies_ms
            )
        if overlay_latencies_ms:
            stage_latencies_ms["text_overlay_max_ms"] = max(
                overlay_latencies_ms
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        stage_latencies_ms["total_ms"] = latency_ms

        poster_images_base64 = [
            encode_image_bytes_to_base64(image_bytes)
            for image_bytes in poster_image_bytes
        ]

        logger.info(
            "image_pipeline_completed | request_id={} | latency_ms={} | poster_count={} | variants={}",
            request_id,
            latency_ms,
            len(poster_images_base64),
            list(zip(applied_variants, [get_variant_image_size(v) for v in applied_variants])),
        )

        return ImageAdResponse(
            request_id=request_id,
            prompt_used=prompt_used,
            num_images=payload.num_images,
            latency_ms=latency_ms,
            generation_mode="direct_poster",
            stage_latencies_ms=stage_latencies_ms,
            images=poster_images_base64,
            background_images=[],
            composite_images=[],
            poster_images=poster_images_base64,
            image_bytes_list=poster_image_bytes,
            applied_variants=applied_variants,
            variant_prompts=variant_prompts,
            food_type=payload.food_type,
            seed=seed or payload.seed,
        )

    except AppException:
        raise

    except Exception as exc:
        logger.exception(
            "image_pipeline_failed | request_id={} | error={}",
            request_id,
            str(exc),
        )
        raise AppException(
            errors.IMAGE_PIPELINE_FAILED,
            detail={
                "request_id": request_id,
                "error": str(exc),
            },
        ) from exc
