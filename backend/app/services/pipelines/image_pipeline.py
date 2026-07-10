from __future__ import annotations

import asyncio
import time
import uuid
from typing import Optional

from loguru import logger
from PIL import Image

from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.schemas.image_ad import GenerationMode, ImageAdRequest, ImageAdResponse
from app.services.providers.factory import get_image_provider
from app.utils.image_bytes import (
    encode_image_bytes_to_base64,
    image_bytes_to_pil,
    pil_image_to_png_bytes,
)


NON_RETRYABLE_ERROR_CODES: set[str] = {
    "HF_IMAGE_PIPELINE_DEPENDENCY_ERROR",
    "HF_IMAGE_MODEL_LOAD_FAILED",
    "HF_TOKEN_MISSING",
    "MODEL_SETTINGS_NOT_FOUND",
    "OPENAI_API_KEY_MISSING",
    "PROVIDER_NOT_SUPPORTED",
}

MOOD_INPAINT_STYLE_MAP: dict[str, str] = {
    "cozy": "warm beige and wood tones, soft natural light, cozy cafe mood",
    "minimal": "bright ivory and gray tones, clean plain background, tidy minimal mood",
    "luxury": "deep brown and charcoal tones, high-contrast lighting, luxurious upscale mood",
    "fresh": "mint and cream tones, bright airy natural light, fresh brunch mood",
    "vintage": "muted beige and brown tones, soft film grain texture, vintage retro mood",
}

LAYOUT_ALIAS_MAP: dict[str, str] = {
    "auto": "auto",
    "classic": "classic",
    "focus": "focus",
    "left": "left",
    "기본": "classic",
    "기본형": "classic",
    "집중형": "focus",
    "포커스": "focus",
    "좌측형": "left",
    "좌측": "left",
}

LAYOUT_POSTER_GUIDE_MAP: dict[str, str] = {
    "classic": "balanced layout: headline on top, price in the middle, hero food shot at the bottom",
    "focus": "minimal typography, food enlarged as the main focal point",
    "left": "food placed left or left-center, text distributed to the right/top for asymmetry",
}

POSTER_PROMPT_HARD_CONSTRAINTS: list[str] = [
    "all rendered text must be Korean only, no English words in the image",
    "place text over high-contrast areas for readability",
    "no cropped text, broken glyphs, typos, repeated characters, or gibberish",
    "no logo, watermark, brand name, signature, or extra decorative text",
    "no humans, people, hands, or body parts in the image",
]

POSTER_RETRY_SUFFIXES: list[str] = [
    "",
    "Retry: prioritize text accuracy and readability, keep the layout simple and stable.",
    "Final retry: clearly separate the 3 text elements at top/center, and place the food as a large hero shot at the bottom.",
]

async def _gather_fail_fast(coros: list) -> list:
    tasks = [asyncio.ensure_future(coro) for coro in coros]

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)

    if pending:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    for task in done:
        exc = task.exception()
        if exc is not None:
            raise exc

    return [task.result() for task in tasks]


def _build_photo_restyle_prompt(payload: ImageAdRequest, mood: str) -> str:
    food_context = getattr(payload, "food", "") or payload.menu_name or "음식"

    prompt_chunks = [
        "Professional restaurant editorial food photography",
        f"food_context : {food_context}"
        "re-photograph the same dish shown in the reference image",
        "preserve the dish identity, portion, garnish, and plate",
        "same tabletop close-up perspective",
        "realistic natural contact shadows and coherent lighting",
        "appetizing food texture, premium commercial food photo",
        "not a cutout, not a collage, not a floating product",
        "no duplicate food, no extra plate, no text, no logo, no watermark",
    ]

    if payload.extra_notes:
        parts.append(f"creative direction: {payload.extra_notes}")

    return ", ".join(parts)


def _build_inpaint_mask_bytes(source_rgba: Image.Image) -> bytes:
    alpha = source_rgba.split()[-1]
    mask = Image.new("RGBA", source_rgba.size, (0, 0, 0, 255))
    mask.putalpha(alpha)
    return pil_image_to_png_bytes(mask)


def _resolve_layout_type(layout_type: Optional[str], index: int) -> str:
    if layout_type:
        normalized = LAYOUT_ALIAS_MAP.get(
            layout_type.strip(),
            LAYOUT_ALIAS_MAP.get(layout_type.replace(" ", "")),
        )

        if normalized and normalized != "auto":
            return normalized

    ordered = ["classic", "focus", "left"]
    return ordered[index % len(ordered)]




def _resolve_generation_mode(mode: GenerationMode | str | None) -> GenerationMode:
    if mode == "two_stage":
        return "two_stage"

    return "direct_poster"


def _build_poster_prompt(payload: ImageAdRequest, layout_type: str) -> str:
    food = (payload.food or "국")
    headline = (payload.headline or "").strip()
    menu_name = payload.menu_name or "오늘의 메뉴"
    price_text = (payload.price_text or "").strip()

    prompt_chunks = [
        "Create a realistic vertical Instagram ad poster based on the input food photo.",
        f"food: {food}"
        "keep the food and plate shape/texture, redesign background, lighting, and composition for the poster",
        "sleek brand advertisement look, avoid a generic template feel",
        "render the text directly in the poster, spelled exactly and correctly",
    ]

    if headline:
        prompt_chunks.append(f"text 1 (top headline): {headline}")
    else:
        prompt_chunks.append(
            "text 1 (top headline): write something natural for the store/promotion context"
        )

    prompt_chunks.extend(
        [
            f"text 2 (menu name, largest): {menu_name}",
            *POSTER_PROMPT_HARD_CONSTRAINTS,
        ]
    )

    if price_text:
        prompt_chunks.append(f"text 3 (price): {price_text}")
        prompt_chunks.append(
            "reproduce the text above exactly, including spacing, punctuation, numbers, and currency symbols"
        )
    else:
        prompt_chunks.append("omit any price text")

    if payload.promotion_goal:
        prompt_chunks.append(f"promotion goal: {payload.promotion_goal}")

    if payload.tone:
        prompt_chunks.append(f"tone: {payload.tone}")

    if payload.extra_notes:
        prompt_chunks.append(f"image request: {payload.image_request}")

    return ", ".join(prompt_chunks)

async def _generate_poster_with_retries(
    *,
    provider,
    source_image_bytes: bytes,
    base_prompt: str,
    mask_image_bytes: bytes | None = None,
    render_mode: str = "photo_restyle",
) -> list[bytes]:
    last_error: Exception | None = None

    for attempt_idx, suffix in enumerate(POSTER_RETRY_SUFFIXES):
        retry_prompt = f"{base_prompt}, {suffix}" if suffix else base_prompt

        try:
            image_bytes_list = await provider.generate(
                input_image_bytes=source_image_bytes,
                mask_image_bytes=mask_image_bytes,
                prompt=retry_prompt,
                num_images=1,
                render_mode=render_mode,
            )

            if image_bytes_list:
                return image_bytes_list

        except AppException as exc:
            if exc.code in NON_RETRYABLE_ERROR_CODES:
                logger.error(
                    "poster_generation_non_retryable_failure | code={} | error={}",
                    exc.code,
                    str(exc),
                )
                raise

            last_error = exc
            logger.warning(
                "poster_generation_attempt_failed | attempt={} | error={}",
                attempt_idx + 1,
                str(exc),
            )

        except Exception as exc:
            last_error = exc
            logger.warning(
                "poster_generation_attempt_failed | attempt={} | error={}",
                attempt_idx + 1,
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
    original_image_bytes: bytes,
    subject_cutout_bytes: bytes | None,
    seed: Optional[int] = None,
) -> ImageAdResponse:
    """
    이미지 광고 생성 파이프라인.
    """

    started = time.perf_counter()
    request_id = f"img-{uuid.uuid4().hex[:10]}"

    if not original_image_bytes:
        raise AppException(
            errors.EMPTY_IMAGE_FILE,
            detail={"request_id": request_id},
        )

    logger.info(
        "image_pipeline_started | request_id={} | mode={} | num_images={} | input_bytes={}",
        request_id,
        payload.generation_mode,
        payload.num_images,
        len(original_image_bytes),
    )

    try:
        original_photo_bytes = pil_image_to_png_bytes(
            image_bytes_to_pil(original_image_bytes).convert("RGB")
        )

        cutout_rgba = image_bytes_to_pil(
            subject_cutout_bytes or original_image_bytes
        ).convert("RGBA")

        cutout_bytes = pil_image_to_png_bytes(cutout_rgba)
        mask_bytes = _build_inpaint_mask_bytes(cutout_rgba)

        provider = get_image_provider()
        generation_mode = _resolve_generation_mode(payload.generation_mode)

        prompt_used = ""
        generated_image_bytes: list[bytes] = []
        generated_image_base64: list[str] = []
        stage_latencies_ms: dict[str, int] = {}

        food_stage_started = time.perf_counter()

        if generation_mode == "two_stage":
            async def _generate_food_image(idx: int) -> tuple[int, str, bytes]:
                current_mood = _resolve_mood_for_index(payload, idx)
                current_prompt = _build_photo_restyle_prompt(payload, current_mood)

                iter_images = await provider.generate(
                    input_image_bytes=original_photo_bytes,
                    mask_image_bytes=None,
                    prompt=current_prompt,
                    num_images=1,
                    render_mode="photo_restyle",
                )
                
                if not iter_images:
                    raise AppException(
                        errors.IMAGE_GENERATION_EMPTY_RESULT,
                        detail={
                            "request_id": request_id,
                            "stage": "food_generation",
                            "index": idx,
                        },
                    )

                return idx, iter_images[0]

            food_results = await _gather_fail_fast(
                [_generate_food_image(idx) for idx in range(payload.num_images)]
            )

            for idx, image_bytes in sorted(food_results, key=lambda item: item[0]):
                generated_image_bytes.append(image_bytes)
                generated_image_base64.append(encode_image_bytes_to_base64(image_bytes))

            if applied_moods:
                prompt_used = _build_photo_restyle_prompt(payload, applied_moods[0])


        stage_latencies_ms["food_generation_ms"] = int(
            (time.perf_counter() - food_stage_started) * 1000
        )

        poster_stage_started = time.perf_counter()

        async def _generate_poster_image(idx: int) -> tuple[int, bytes, str]:
            source_for_poster = (
                generated_image_bytes[idx]
                if generation_mode == "two_stage"
                else cutout_bytes
            )

            if generation_mode == "two_stage":
                return idx, source_for_poster, "photo_restyle"

            resolved_layout = _resolve_layout_type(payload.layout_type, idx)

            poster_payload = ImageAdRequest(
                **{
                    **payload.model_dump(),
                }
            )

            poster_prompt = _build_poster_prompt(
                payload=poster_payload,
                layout_type=resolved_layout,
            )

            poster_outputs = await _generate_poster_with_retries(
                provider=provider,
                source_image_bytes=source_for_poster,
                base_prompt=poster_prompt,
                mask_image_bytes=mask_bytes if generation_mode == "direct_poster" else None,
                render_mode="background_swap",
            )

            if not poster_outputs:
                raise AppException(
                    errors.IMAGE_GENERATION_EMPTY_RESULT,
                    detail={
                        "request_id": request_id,
                        "stage": "poster_generation",
                        "index": idx,
                    },
                )

            return idx, poster_outputs[0], poster_prompt

        poster_results = await _gather_fail_fast(
            [_generate_poster_image(idx) for idx in range(payload.num_images)]
        )

        poster_image_bytes: list[bytes] = []
        for idx, poster_bytes, poster_prompt in sorted(poster_results, key=lambda item: item[0]):
            poster_image_bytes.append(poster_bytes)

            if not prompt_used:
                prompt_used = poster_prompt

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
            "image_pipeline_completed | request_id={} | latency_ms={} | poster_count={}",
            request_id,
            latency_ms,
            len(poster_images_base64),
        )

        return ImageAdResponse(
            request_id=request_id,
            prompt_used=prompt_used,
            num_images=payload.num_images,
            latency_ms=latency_ms,
            generation_mode=generation_mode,
            stage_latencies_ms=stage_latencies_ms,
            images=poster_images_base64,
            background_images=[],
            composite_images=generated_image_base64,
            poster_images=poster_images_base64,
            image_bytes_list=poster_image_bytes,
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
