"""
이미지 출력 유형(studio / poster / instagram_feed)별 프롬프트 빌더.

음식 유형(food_type)과 출력 유형(variant) 조합으로 프롬프트를 분기한다.
"""

from __future__ import annotations

from app.schemas.food_type import FoodType
from app.schemas.image_ad import ImageAdRequest, ImageVariantType
from app.services.pipelines.food_type_prompts import (
    build_food_variant_prompt,
    build_variant_negative_prompt,
    strip_prompt_neg_line,
)
from app.services.providers.base import ImageRenderMode


def build_variant_prompt(
    payload: ImageAdRequest,
    variant: ImageVariantType,
    *,
    food_type: FoodType,
) -> str:
    return build_food_variant_prompt(
        payload,
        variant,
        food_type=food_type,
    )


def resolve_variant_render_mode(
    variant: ImageVariantType,
    *,
    image_provider: str,
) -> ImageRenderMode:
    """
    변형 유형과 provider에 따라 렌더 모드를 선택한다.

    OpenAI → images.edit (photo_restyle)
    HF/FLUX → studio/poster는 background_swap (음식 보존 + 배경만 교체),
              instagram_feed(릴스)는 photo_restyle (매장 배경 보존 후 클로즈업)
    """
    if image_provider == "hf" and variant in ("studio", "poster"):
        return "background_swap"
    return "photo_restyle"


# HF img2img — variant별 strength (높을수록 배경·장면 변경 ↑, 음식 보존 ↓)
_HF_VARIANT_IMG2IMG_STRENGTH: dict[ImageVariantType, float] = {
    "studio": 0.68,
    "poster": 0.65,
    "instagram_feed": 0.45,
}


def resolve_hf_img2img_strength(
    variant: ImageVariantType,
    *,
    default_strength: float,
) -> float:
    return _HF_VARIANT_IMG2IMG_STRENGTH.get(variant, default_strength)


def build_hf_variant_prompts(
    payload: ImageAdRequest,
    variant: ImageVariantType,
    *,
    food_type: FoodType,
) -> tuple[str, str]:
    """HF용 (positive_prompt, negative_prompt) — NEG 줄은 negative 파라미터로 분리."""
    full_prompt = build_variant_prompt(
        payload,
        variant,
        food_type=food_type,
    )
    return strip_prompt_neg_line(full_prompt), build_variant_negative_prompt(variant)
