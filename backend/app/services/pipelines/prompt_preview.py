"""
이미지 생성 프롬프트 미리보기/테스트용 유틸.

UI·API 연결 없이 food_type × variant 조합 프롬프트만 확인할 때 사용한다.

사용 예:
    cd backend
    python scripts/preview_image_prompts.py
    python scripts/preview_image_prompts.py --food-type fried --variant studio
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.food_type import FOOD_TYPE_LABELS, FoodType
from app.schemas.image_ad import DEFAULT_IMAGE_VARIANTS, ImageAdRequest, ImageVariantType
from app.services.pipelines.food_type_prompts import (
    build_food_variant_prompt,
    uses_custom_template,
)
from app.services.pipelines.hf_food_type_prompts import (
    build_hf_food_variant_prompt,
    uses_hf_custom_template,
)


@dataclass(frozen=True)
class PromptPreviewSample:
    store_name: str = "만월 카페"
    menu_name: str = "시그니처 메뉴"
    purpose: str = "신메뉴 홍보"
    tone: str = "캐주얼·친근"
    request_note: str = ""
    headline: str = "오늘 저녁은 든든하게"
    price_text: str = "12,000원"
    store_location: str = "서울 마포구"


def build_sample_payload(
    food_type: FoodType,
    sample: PromptPreviewSample | None = None,
) -> ImageAdRequest:
    sample = sample or PromptPreviewSample()

    return ImageAdRequest(
        store_name=sample.store_name,
        menu_name=sample.menu_name,
        store_location=sample.store_location or None,
        food_type=food_type,
        promotion_goal=sample.purpose,
        tone=sample.tone,
        extra_notes=sample.request_note,
        headline=sample.headline or None,
        price_text=sample.price_text or None,
        num_images=3,
        generation_mode="direct_poster",
    )


def preview_image_prompt(
    food_type: FoodType,
    variant: ImageVariantType,
    *,
    sample: PromptPreviewSample | None = None,
    provider: str = "openai",
) -> str:
    payload = build_sample_payload(food_type, sample=sample)
    if provider == "hf":
        return build_hf_food_variant_prompt(
            payload,
            variant,
            food_type=food_type,
        )
    return build_food_variant_prompt(
        payload,
        variant,
        food_type=food_type,
    )


def iter_prompt_previews(
    *,
    sample: PromptPreviewSample | None = None,
    provider: str = "openai",
) -> list[tuple[FoodType, ImageVariantType, str, bool]]:
    """
    (food_type, variant, prompt, uses_custom_template) 목록을 반환한다.
    """

    rows: list[tuple[FoodType, ImageVariantType, str, bool]] = []

    for food_type in FOOD_TYPE_LABELS:
        for variant in DEFAULT_IMAGE_VARIANTS:
            prompt = preview_image_prompt(food_type, variant, sample=sample, provider=provider)
            uses_template = (
                uses_hf_custom_template(food_type, variant)
                if provider == "hf"
                else uses_custom_template(food_type, variant)
            )
            rows.append(
                (
                    food_type,
                    variant,
                    prompt,
                    uses_template,
                )
            )

    return rows


def format_prompt_preview(
    food_type: FoodType,
    variant: ImageVariantType,
    prompt: str,
    *,
    uses_template: bool,
    provider: str = "openai",
) -> str:
    source = "custom_template" if uses_template else "fallback"
    label = FOOD_TYPE_LABELS[food_type]
    header = f"[{provider}] [{food_type} / {label}] × [{variant}] ({source})"
    separator = "=" * min(len(header), 80)
    return f"{header}\n{separator}\n{prompt}\n"
