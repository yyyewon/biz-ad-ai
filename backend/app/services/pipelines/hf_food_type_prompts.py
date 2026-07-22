"""
HF image generation prompts (Stable Diffusion img2img).

OpenAI path uses food_type_prompts.py.
HF tuning·실험은 이 파일만 수정한다 — OpenAI 프롬프트와 분리된 single source of truth.

시작점:
- HF_FOOD_VARIANT_PROMPT_TEMPLATES 는 OpenAI 템플릿을 복사해 두었음.
- HF 전용 문구로 바꿀 때는 아래 registry·negative 블록만 편집하면 된다.
"""

from __future__ import annotations

from app.schemas.food_type import FoodType
from app.schemas.image_ad import ImageAdRequest, ImageVariantType
from app.services.pipelines import food_type_prompts as openai_prompts

# =============================================================================
# HF template registry
# =============================================================================

HF_FOOD_VARIANT_PROMPT_TEMPLATES: dict[tuple[FoodType, ImageVariantType], str] = dict(
    openai_prompts.FOOD_VARIANT_PROMPT_TEMPLATES
)


def render_hf_food_variant_prompt_template(
    payload: ImageAdRequest,
    *,
    food_type: FoodType,
    variant: ImageVariantType,
) -> str | None:
    template = HF_FOOD_VARIANT_PROMPT_TEMPLATES.get((food_type, variant), "").strip()
    if not template:
        return None

    context = openai_prompts.build_template_context(
        payload,
        food_type=food_type,
        variant=variant,
    )
    return template.format(**context)


def build_hf_food_variant_prompt(
    payload: ImageAdRequest,
    variant: ImageVariantType,
    *,
    food_type: FoodType,
) -> str:
    custom_prompt = render_hf_food_variant_prompt_template(
        payload,
        food_type=food_type,
        variant=variant,
    )
    if not custom_prompt:
        raise ValueError(
            f"No HF prompt template for food_type={food_type!r}, variant={variant!r}"
        )
    return custom_prompt


def build_hf_variant_negative_prompt(variant: ImageVariantType) -> str:
    """HF img2img negative_prompt. OpenAI와 달라질 수 있음."""

    return openai_prompts.build_variant_negative_prompt(variant)


def strip_prompt_neg_line(prompt: str) -> str:
    """positive prompt에서 NEG: 줄을 제거한다 (HF negative 파라미터로 분리)."""

    lines = [line for line in prompt.splitlines() if not line.strip().startswith("NEG:")]
    return "\n".join(lines).strip()
