"""
이미지 출력 유형(studio / poster / instagram_feed)별 프롬프트 빌더.

음식 유형(food_type)과 출력 유형(variant) 조합으로 프롬프트를 분기한다.
"""

from __future__ import annotations

from typing import Callable

from app.schemas.food_type import FoodType
from app.schemas.image_ad import ImageAdRequest, ImageVariantType
from app.services.pipelines.food_type_prompts import build_food_variant_prompt

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
