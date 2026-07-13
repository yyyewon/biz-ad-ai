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
    GenerationMode,
    ImageAdRequest,
    ImageAdResponse,
    ImageVariantType,
)
from app.core.model_config import get_variant_image_size
from app.services.pipelines.food_type_prompts import (
    _build_user_priority_block,
    build_food_context_line,
    build_poster_exact_text_block,
    uses_custom_template,
)
from app.services.pipelines.image_variant_prompts import build_variant_prompt
from app.services.providers.factory import get_image_provider
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


DEFAULT_IMAGE_STYLE = (
    "따뜻한 베이지/우드 계열 색감, 부드러운 자연광, 아늑한 카페 분위기"
)


def _prepare_edit_source_bytes(
    source_bytes: bytes,
    *,
    food_type: str | None,
    variant: ImageVariantType,
) -> bytes:
    """
    OpenAI images.edit 입력용 소스 이미지를 준비한다.

    - studio: 축소·패딩으로 미디엄 와이드 구도 유도
    - instagram_feed: 중앙 줌으로 릴스용 음식 클로즈업 유도
    """

    image = image_bytes_to_pil(source_bytes).convert("RGB")

    if food_type and uses_custom_template(food_type, variant):
        if variant == "studio":
            image = shrink_and_pad_for_wider_framing(image)
        elif variant == "instagram_feed":
            image = zoom_center_crop(image)

        logger.info(
            "image_edit_source_reframed | food_type={} | variant={} | size={}",
            food_type,
            variant,
            image.size,
        )

    return pil_image_to_png_bytes(image)


LAYOUT_POSTER_GUIDE_MAP: dict[str, str] = {
    "classic": "상단 텍스트, 중앙 가격 포인트, 하단 음식 히어로 이미지의 균형 잡힌 정석형 구도",
    "focus": "타이포를 간결하게 두고 음식을 더 크게 강조하는 집중형 구도",
    "left": "음식을 좌측 또는 좌중앙에 배치하고 텍스트를 우측/상단으로 분산한 비대칭 구도",
}

POSTER_PROMPT_HARD_CONSTRAINTS: list[str] = [
    "반드시 1080x1350 비율의 세로 포스터 디자인으로 생성해줘.",
    "텍스트는 오직 한국어만 사용하고, 임의 영문 문구는 절대 넣지 마.",
    "가독성이 낮은 배경 위에 텍스트를 두지 말고, 텍스트 영역은 대비를 충분히 확보해줘.",
    "잘린 텍스트, 깨진 글자, 오탈자, 반복 글자, 의미 없는 문자는 절대 넣지 마.",
    "로고, 워터마크, 브랜드명, 서명, 불필요한 장식 문구를 넣지 마.",
]

POSTER_RETRY_SUFFIXES: list[str] = [
    "",
    "재시도: 맨 아래 [반드시 그대로 표기] 문구를 오타·깨짐 없이 정확히 다시 렌더링. 레이아웃은 단순하게.",
    "최종 재시도: [반드시 그대로 표기]의 각 문구를 상단 가운데·하단 우측에 분리 배치. 음식은 하단 히어로 컷.",
]


def _build_inpaint_prompt(payload: ImageAdRequest) -> str:
    prompt_chunks: list[str] = []

    priority_block = _build_user_priority_block(payload.extra_notes or "")
    if priority_block:
        prompt_chunks.append(priority_block)

    prompt_chunks.extend(
        [
            "업로드된 음식 사진을 기반으로 광고용 푸드 이미지를 자연스럽게 개선해줘.",
            DEFAULT_IMAGE_STYLE,
            "메인 메뉴와 함께 보이는 반찬, 접시, 테이블 구성은 최대한 유지해줘.",
            "실사 기반의 상업용 푸드 포토그래피 느낌으로 생성해줘.",
            "문구를 넣을 수 있도록 여백이 있는 깔끔한 구도로 만들어줘.",
            "최종 색감/조명 분위기는 반드시 위의 스타일과 일치시켜줘.",
            "이미지 안에 글자, 영문 단어, 메뉴명, 로고, 워터마크를 절대 넣지 마.",
            "추가 음식, 중복 접시, 잘린 접시를 만들지 마.",
        ]
    )

    if payload.food_type:
        prompt_chunks.append(build_food_context_line(payload.food_type))

    if payload.promotion_goal:
        prompt_chunks.append(f"홍보 목적 맥락: {payload.promotion_goal}")

    if payload.tone:
        prompt_chunks.append(f"전반적인 문체/분위기: {payload.tone}")

    if payload.prompt:
        prompt_chunks.append(f"사용자 직접 프롬프트: {payload.prompt}")

    return ", ".join(prompt_chunks)


def _resolve_image_variant(index: int) -> ImageVariantType:
    return DEFAULT_IMAGE_VARIANTS[index % len(DEFAULT_IMAGE_VARIANTS)]


def _resolve_generation_mode(mode: GenerationMode | str | None) -> GenerationMode:
    if mode == "two_stage":
        return "two_stage"

    return "direct_poster"


def _build_poster_prompt(payload: ImageAdRequest, layout_type: str) -> str:
    layout_guide = LAYOUT_POSTER_GUIDE_MAP.get(
        layout_type,
        LAYOUT_POSTER_GUIDE_MAP["classic"],
    )

    headline = (payload.headline or "").strip()
    if not headline:
        headline = resolve_poster_headline_from_purpose(payload.promotion_goal or "")
    menu_name = payload.menu_name or "오늘의 메뉴"
    price_text = (payload.price_text or "").strip()
    store_name = (payload.store_name or "").strip()

    prompt_chunks: list[str] = []

    priority_block = _build_user_priority_block(payload.extra_notes or "")
    if priority_block:
        prompt_chunks.append(priority_block)

    prompt_chunks.extend(
        [
            "입력된 음식 사진을 기반으로 인스타그램용 세로 광고 포스터를 실사 스타일로 만들어줘.",
            f"포스터 스타일: {DEFAULT_IMAGE_STYLE}",
            f"레이아웃 가이드: {layout_guide}",
            "음식과 접시의 형태/재질은 유지하고 배경, 조명, 구도는 포스터 디자인에 맞게 새롭게 구성해줘.",
            "상단 가운데에 카피·메뉴명·가격, 하단 우측에 가게명을 포스터 디자인에 포함해 한국어로 직접 그려줘.",
            *POSTER_PROMPT_HARD_CONSTRAINTS,
            "텍스트는 가독성이 높아야 하고 음식을 과도하게 가리지 않게 배치해줘.",
            "로고, 워터마크, 불필요한 장식 문구를 넣지 마.",
        ]
    )

    if payload.promotion_goal:
        prompt_chunks.append(f"홍보 목적 맥락: {payload.promotion_goal}")

    if payload.tone:
        prompt_chunks.append(f"전반적인 문체/분위기: {payload.tone}")

    if payload.prompt:
        prompt_chunks.append(f"사용자 직접 프롬프트: {payload.prompt}")

    exact_block = build_poster_exact_text_block(
        headline=headline,
        menu_name=menu_name,
        price_text=price_text,
        store_name=store_name,
    )

    return ", ".join(prompt_chunks) + "\n\n" + exact_block


async def _generate_poster_with_retries(
    *,
    provider,
    source_image_bytes: bytes,
    base_prompt: str,
    mask_image_bytes: bytes | None = None,
    size: str | None = None,
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
                size=size,
            )

            if image_bytes_list:
                return image_bytes_list

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
        "image_pipeline_started | request_id={} | mode={} | num_images={} | food_type={} | input_bytes={}",
        request_id,
        payload.generation_mode,
        payload.num_images,
        payload.food_type,
        len(source_image_bytes),
    )

    try:
        source_rgb = image_bytes_to_pil(source_image_bytes).convert("RGB")
        prepared_source_bytes = pil_image_to_png_bytes(source_rgb)

        provider = get_image_provider()
        generation_mode = _resolve_generation_mode(payload.generation_mode)

        prompt_used = ""
        generated_image_bytes: list[bytes] = []
        generated_image_base64: list[str] = []
        stage_latencies_ms: dict[str, int] = {}

        food_stage_started = time.perf_counter()

        if generation_mode == "two_stage":
            async def _generate_food_image(idx: int) -> tuple[int, bytes]:
                current_prompt = _build_inpaint_prompt(payload)

                iter_images = await provider.generate(
                    input_image_bytes=prepared_source_bytes,
                    prompt=current_prompt,
                    num_images=1,
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

            food_results = await asyncio.gather(
                *[
                    _generate_food_image(idx)
                    for idx in range(payload.num_images)
                ]
            )

            for idx, image_bytes in sorted(food_results, key=lambda item: item[0]):
                generated_image_bytes.append(image_bytes)
                generated_image_base64.append(encode_image_bytes_to_base64(image_bytes))

                if not prompt_used:
                    prompt_used = _build_inpaint_prompt(payload)

        stage_latencies_ms["food_generation_ms"] = int(
            (time.perf_counter() - food_stage_started) * 1000
        )

        poster_stage_started = time.perf_counter()

        async def _generate_variant_image(idx: int) -> tuple[int, ImageVariantType, bytes, str]:
            source_for_variant = (
                generated_image_bytes[idx]
                if generation_mode == "two_stage"
                else prepared_source_bytes
            )

            variant = _resolve_image_variant(idx)
            variant_size = get_variant_image_size(variant)
            variant_prompt = build_variant_prompt(
                payload,
                variant,
                food_type=payload.food_type,
                build_poster_prompt=_build_poster_prompt,
            )
            edit_source_bytes = _prepare_edit_source_bytes(
                source_for_variant,
                food_type=payload.food_type,
                variant=variant,
            )

            variant_outputs = await _generate_poster_with_retries(
                provider=provider,
                source_image_bytes=edit_source_bytes,
                base_prompt=variant_prompt,
                size=variant_size,
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
            generation_mode=generation_mode,
            stage_latencies_ms=stage_latencies_ms,
            images=poster_images_base64,
            background_images=[],
            composite_images=generated_image_base64,
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
