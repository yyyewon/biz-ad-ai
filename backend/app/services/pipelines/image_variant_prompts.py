"""
이미지 출력 유형(studio / poster / instagram_feed)별 프롬프트 빌더.

음식 유형(food_type)과 출력 유형(variant) 조합으로 프롬프트를 분기한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.food_type import FoodType
from app.schemas.image_ad import ImageAdRequest, ImageVariantType
from app.services.pipelines.food_type_prompts import build_food_variant_prompt
from app.services.providers.base import ImageRenderMode


@dataclass(frozen=True)
class SDXLPrompt:
    prompt: str
    prompt_2: str | None
    negative_prompt: str


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
    OpenAI는 기존 images.edit 경로를 유지한다.
    HF studio/poster는 전경 보존 Inpaint, instagram_feed만 img2img를 사용한다.
  """
    if image_provider == "hf" and variant in ("studio", "poster"):
        return "background_swap"
    return "photo_restyle"


# HF img2img — variant별 strength (높을수록 배경·장면 변경 ↑, 음식 보존 ↓)
_HF_VARIANT_IMG2IMG_STRENGTH: dict[ImageVariantType, float] = {
    "studio": 0.42,
    "poster": 0.42,
    "instagram_feed": 0.30,
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
) -> SDXLPrompt:
    """Build compact SDXL prompts without Korean labels or PIL typography rules."""

    _ = payload
    subject = {
        "soup_stew": "the same plated soup or stew",
        "fried": "the same plated fried food",
        "grilled_bbq": "the same plated grilled food",
        "rice_dish": "the same plated rice dish",
        "bread_dessert": "the same plated bread or dessert",
        "burger_sandwich": "the same plated burger or sandwich",
        "coffee_drink": "the same prepared coffee or drink",
    }[food_type]

    if variant == "studio":
        prompt = (
            f"commercial studio food photo of {subject}, faithful shape and texture, "
            "clean warm neutral tabletop, soft diffused side light, realistic camera texture, "
            "uncluttered background"
        )
    elif variant == "poster":
        prompt = (
            f"minimal vertical advertisement background for {subject}, simple tonal gradient, "
            "soft studio lighting, clean empty upper area, subtle surface below, no interior scene"
        )
    else:
        prompt = (
            f"authentic smartphone cafe photo of {subject}, natural warm light, clearer food texture, "
            "realistic in-store atmosphere, subtle depth of field, natural colors"
        )

    negative_prompt = (
        "text, letters, numbers, logo, watermark, duplicate food, deformed food, "
        "distorted plate, extra dish, plastic texture, CGI, oversaturated, blurry, low quality"
    )
    return SDXLPrompt(
        prompt=_limit_sdxl_tokens(prompt),
        prompt_2="realistic food photography, natural materials, controlled light",
        negative_prompt=negative_prompt,
    )


def _limit_sdxl_tokens(prompt: str, *, limit: int = 75) -> str:
    """Conservative word-based guard before provider tokenizer validation."""

    words = prompt.split()
    if len(words) <= limit:
        return prompt
    return " ".join(words[:limit])
