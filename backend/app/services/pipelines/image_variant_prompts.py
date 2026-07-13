"""
이미지 출력 유형(studio / poster / instagram_feed)별 프롬프트 빌더.

음식 유형(food_type)과 출력 유형(variant) 조합으로 프롬프트를 분기한다.
"""

from __future__ import annotations

from typing import Callable

from app.schemas.food_type import FoodType
from app.schemas.image_ad import ImageAdRequest, ImageVariantType
from app.services.pipelines.food_type_prompts import (
    build_food_variant_prompt,
    build_variant_negative_prompt,
    strip_prompt_neg_line,
)
from app.services.providers.base import ImageRenderMode

# 레거시 레이아웃 프롬프트 임시 매핑 (fallback 경로에서만 사용)
VARIANT_LAYOUT_MAP: dict[ImageVariantType, str] = {
    "studio": "focus",
    "poster": "classic",
    "instagram_feed": "left",
}


def build_variant_prompt(
    payload: ImageAdRequest,
    variant: ImageVariantType,
    *,
    food_type: FoodType,
    build_poster_prompt: Callable[[ImageAdRequest, str], str],
) -> str:
    return build_food_variant_prompt(
        payload,
        variant,
        food_type=food_type,
        build_poster_prompt=build_poster_prompt,
    )


def resolve_variant_render_mode(
    variant: ImageVariantType,
    *,
    image_provider: str,
) -> ImageRenderMode:
    """
    OpenAI·HF 공통: 업로드 사진 전체를 variant 프롬프트로 재생성(photo_restyle).

    OpenAI → images.edit, HF → img2img. rembg 누끼·배경 합성(background_swap)은 사용하지 않는다.
    """
    _ = (variant, image_provider)
    return "photo_restyle"


def build_hf_variant_prompts(
    payload: ImageAdRequest,
    variant: ImageVariantType,
    *,
    food_type: FoodType,
    build_poster_prompt: Callable[[ImageAdRequest, str], str],
) -> tuple[str, str]:
    """HF용 (positive_prompt, negative_prompt) — NEG 줄은 negative 파라미터로 분리."""
    full_prompt = build_variant_prompt(
        payload,
        variant,
        food_type=food_type,
        build_poster_prompt=build_poster_prompt,
    )
    return strip_prompt_neg_line(full_prompt), build_variant_negative_prompt(variant)
