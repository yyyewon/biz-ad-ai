from __future__ import annotations

import asyncio
import time
import uuid
from typing import Optional

from loguru import logger

from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.schemas.image_ad import (
    DEFAULT_IMAGE_VARIANTS,
    ImageAdRequest,
    ImageAdResponse,
    ImageVariantType,
)
from app.core.model_config import get_provider_name, get_variant_image_size, get_model_settings
from app.services.pipelines.food_type_prompts import uses_custom_template
from app.services.pipelines.image_variant_prompts import (
    build_hf_variant_prompts,
    build_variant_prompt,
    resolve_hf_img2img_strength,
    resolve_variant_render_mode,
)
from app.services.providers.base import ImageRenderMode
from app.services.providers.factory import get_image_provider
from app.utils.image_processor import shrink_and_pad_for_wider_framing, zoom_center_crop, generate_cutout_mask
from app.utils.image_bytes import (
    encode_image_bytes_to_base64,
    image_bytes_to_pil,
    pil_image_to_png_bytes,
)
from app.utils.image_text_overlay import (
    apply_variant_text_overlay,
    variant_uses_pil_text_overlay,
)


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

    if food_type and uses_custom_template(food_type, variant):
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


def _apply_reframe_to_mask(
    mask_bytes: bytes,
    *,
    food_type: str | None,
    variant: ImageVariantType,
) -> bytes:
    """
    누끼 마스크 이미지를 소스 이미지와 동일한 리프레임 규칙으로 변환한다.

    background_swap 시 마스크와 소스의 구도가 정확히 일치해야 한다.
    """

    image = image_bytes_to_pil(mask_bytes)

    if food_type and uses_custom_template(food_type, variant):
        if variant == "studio":
            image = shrink_and_pad_for_wider_framing(image)
        elif variant == "instagram_feed":
            image = zoom_center_crop(image, zoom_factor=1.28)

    return pil_image_to_png_bytes(image)


POSTER_RETRY_SUFFIXES: list[str] = [
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
    mask_image_bytes: bytes | None = None,
    size: str | None = None,
    render_mode: ImageRenderMode = "photo_restyle",
    negative_prompt: str | None = None,
    img2img_strength: float | None = None,
) -> list[bytes]:
    last_error: Exception | None = None

    for attempt_idx, suffix in enumerate(POSTER_RETRY_SUFFIXES):
        retry_prompt = f"{base_prompt}, {suffix}" if suffix else base_prompt

        try:
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

            image_bytes_list = await provider.generate(**generate_kwargs)

            if image_bytes_list:
                return image_bytes_list

        except Exception as exc:
            last_error = exc
            logger.warning(
                "poster_generation_attempt_failed | attempt={} | render_mode={} | error={}",
                attempt_idx + 1,
                render_mode,
                str(exc),
            )

    raise AppException(
        errors.IMAGE_POSTER_RETRY_FAILED,
        detail={
            "attempt_count": len(POSTER_RETRY_SUFFIXES),
            "last_error": str(last_error) if last_error else None,
        },
    )


async def generate_image_ads(
    payload: ImageAdRequest,
    source_image_bytes: bytes,
    seed: Optional[int] = None,
) -> ImageAdResponse:
    """
    이미지 광고 생성 파이프라인.

    메모리 기반 처리 기준:
    - 입력 이미지는 bytes로 받는다.
    - 전처리 source/mask/poster 이미지를 서버 디스크에 저장하지 않는다.
    - provider는 list[bytes]를 반환한다.
    - API 응답용 이미지는 base64 문자열로 변환한다.
    - 포스터/스튜디오/인스타피드 유형별로 num_images 개수만큼 asyncio.gather로 병렬 실행한다.
    """

    started = time.perf_counter()
    request_id = f"img-{uuid.uuid4().hex[:10]}"

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

        prompt_used = ""
        stage_latencies_ms: dict[str, int] = {}

        poster_stage_started = time.perf_counter()

        async def _generate_variant_image(idx: int) -> tuple[int, ImageVariantType, bytes, str]:
            variant = _resolve_image_variant(idx)
            variant_size = get_variant_image_size(variant)
            render_mode = resolve_variant_render_mode(
                variant,
                image_provider=image_provider_name,
            )

            if image_provider_name == "hf":
                variant_prompt, negative_prompt = build_hf_variant_prompts(
                    payload,
                    variant,
                    food_type=payload.food_type,
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

            # background_swap 모드에서는 음식(피사체) 누끼 마스크를 생성해 provider에 전달.
            # 마스크 생성 실패 시 photo_restyle로 폴백.
            mask_bytes_for_swap: bytes | None = None
            if render_mode == "background_swap":
                raw_mask = generate_cutout_mask(source_image_bytes)
                if raw_mask is not None:
                    mask_bytes_for_swap = _apply_reframe_to_mask(
                        raw_mask,
                        food_type=payload.food_type,
                        variant=variant,
                    )
                else:
                    render_mode = "photo_restyle"
                    logger.warning(
                        "image_mask_generation_failed_fallback | variant={} | render_mode=photo_restyle",
                        variant,
                    )

            img2img_strength: float | None = None
            if image_provider_name == "hf":
                hf_settings = get_model_settings(
                    role="image_generation",
                    provider_name="hf",
                )["settings"]
                default_strength = float(
                    hf_settings.get("img2img_restyle_strength", 0.45)
                )
                img2img_strength = resolve_hf_img2img_strength(
                    variant,
                    default_strength=default_strength,
                )

            logger.info(
                "image_variant_generation_started | variant={} | provider={} | render_mode={} | has_mask={} | img2img_strength={}",
                variant,
                image_provider_name,
                render_mode,
                mask_bytes_for_swap is not None,
                img2img_strength,
            )

            variant_outputs = await _generate_poster_with_retries(
                provider=provider,
                source_image_bytes=edit_source_bytes,
                base_prompt=variant_prompt,
                mask_image_bytes=mask_bytes_for_swap,
                size=variant_size,
                render_mode=render_mode,
                negative_prompt=negative_prompt,
                img2img_strength=img2img_strength,
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

            return idx, variant, variant_outputs[0], variant_prompt

        variant_results = await asyncio.gather(
            *[
                _generate_variant_image(idx)
                for idx in range(payload.num_images)
            ]
        )

        poster_image_bytes: list[bytes] = []
        applied_variants: list[ImageVariantType] = []
        for idx, variant, poster_bytes, variant_prompt in sorted(
            variant_results,
            key=lambda item: item[0],
        ):
            if variant_uses_pil_text_overlay(payload.food_type, variant):
                poster_bytes = apply_variant_text_overlay(
                    poster_bytes,
                    payload=payload,
                    variant=variant,
                )
                logger.info(
                    "image_text_overlay_applied | variant={} | food_type={}",
                    variant,
                    payload.food_type,
                )

            poster_image_bytes.append(poster_bytes)
            applied_variants.append(variant)

            if not prompt_used:
                prompt_used = variant_prompt

        stage_latencies_ms["poster_generation_ms"] = int(
            (time.perf_counter() - poster_stage_started) * 1000
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
