"""
HF image generation prompts (Boogu-Image-0.1-Edit TI2I).

OpenAI 경로: food_type_prompts.py
HF 경로: 이 파일만 수정한다. OpenAI fallback 없음 — 비어 있으면 즉시 오류.

Boogu Edit는 CLIP comma tag가 아니라 **자연어 edit instruction** 을 사용한다.
positive → `instruction`, negative → `negative_instruction` (provider 분리).

Read order (food_type_prompts.py 와 동일):
    Meta · hints
    0. Global shared blocks (negative, realism)
    1. Studio — template + per food-type subject/scene
    2. Poster — layout + per food-type food/background
    3. Reels (instagram_feed)
    4. Template registry
    Public API

Preview:
    cd backend
    python scripts/preview_image_prompts.py --provider hf --food-type fried --variant poster
"""

from __future__ import annotations

from app.schemas.food_type import FOOD_TYPE_LABELS, FoodType
from app.schemas.image_ad import ImageAdRequest, ImageVariantType
from app.services.pipelines import food_type_prompts as openai_prompts
from app.utils.poster_taglines import resolve_poster_headline


# =============================================================================
# Meta · hints (참고용 — OpenAI 와 동일 값)
# =============================================================================

VARIANT_LABELS = openai_prompts.VARIANT_LABELS
FOOD_TYPE_SCENE_HINTS = openai_prompts.FOOD_TYPE_SCENE_HINTS
VARIANT_DIRECTION_HINTS = openai_prompts.VARIANT_DIRECTION_HINTS


def _require_hf(value: str | None, name: str) -> str:
    if value is None or not str(value).strip():
        raise ValueError(
            f"HF prompt constant {name!r} is empty — fill it in hf_food_type_prompts.py"
        )
    return str(value).strip()


def _sentence(*parts: str) -> str:
    """Join non-empty fragments into one instruction sentence block."""
    cleaned = [part.strip().rstrip(".") for part in parts if part and part.strip()]
    if not cleaned:
        return ""
    return ". ".join(cleaned) + "."


# =============================================================================
# 0. Global shared blocks
# =============================================================================

HF_REALISM_RULES = _sentence(
    "Keep a real camera editorial food photo look with natural texture, gloss, and grain",
    "Add steam only if the dish is hot",
    "Do not use CGI, plastic sheen, HDR, neon colors, or beauty-filter smoothing",
)

HF_NEGATIVE_CLUTTER = _sentence(
    "Do not keep empty plates, water cups or glasses, napkins, call bells, receipts, "
    "or unrelated drinks and table clutter",
)

HF_NEGATIVE_COMMON = _sentence(
    "Do not add text, numbers, logos, watermarks, UI, dish names, menu titles, captions, "
    "or subtitles anywhere in the image",
    HF_NEGATIVE_CLUTTER,
)

HF_NEGATIVE_POSTER = _sentence(
    "Do not add any letters, numbers, prices, Korean menu titles, dish names, store labels, "
    "English words such as STORE, NAME, MENU, or PRICE, addresses, logos, watermarks, UI, "
    "captions, subtitles, price badges, or placeholder typography in the image pixels",
    "Typography will be added later in post-processing, so the generated image must contain zero words",
    "Do not use a cafe interior, dining room, brick wall, wood-table photo, or decorative pattern "
    "in the upper text zone",
    "Do not vertically center the food hero or let food occupy the upper 40% of the frame",
    "Do not create an oversized soup pot or giant ttukbaegi close-up filling the frame",
    HF_NEGATIVE_CLUTTER,
)

HF_NEGATIVE_REELS = _sentence(
    HF_NEGATIVE_COMMON,
    "Do not add hook text, captions, Korean or English letters, menu titles, prices, "
    "or store labels in the image pixels",
)

HF_NEGATIVE_STUDIO = _sentence(
    HF_NEGATIVE_COMMON,
    "Do not add exaggerated gloss, oil, smoke, steam, toppings, foam, cream, or condensation "
    "that is not in the original photo",
    "Do not oversaturate food colors",
)

_HF_PRESERVE_FOOD_BASE = _sentence(
    "Preserve the main menu item, its toppings, and its serving vessel exactly as in the reference photo",
    "Do not add or remove food items, and do not float or crop the vessel unnaturally",
)

_HF_EXCLUDE_TABLE_CLUTTER = _sentence(
    "Remove empty plates, water cups and glasses, napkins, call bells, menus, unrelated drinks, "
    "and other table clutter from the scene",
)

_HF_SUBJECT_HERO_COMMON = _sentence(
    _HF_PRESERVE_FOOD_BASE,
    "Keep the ordered menu item as the clear hero subject",
    _HF_EXCLUDE_TABLE_CLUTTER,
)

_HF_STUDIO_SCENE_BASE = _sentence(
    "Replace the casual dining setup with a clean studio food-photo look",
    "Use a tidy surface, soft even professional lighting, and an uncluttered background",
    "Use medium-wide framing with the food occupying about 55-65% of the frame",
    "Do not include people",
)

_HF_STUDIO_FOOD_BASE = _sentence(
    _HF_PRESERVE_FOOD_BASE,
    "Keep the ordered menu item as the hero subject and preserve its appearance faithfully",
    _HF_EXCLUDE_TABLE_CLUTTER,
)

_HF_POSTER_FOOD_BASE = _sentence(
    "Preserve the original main dish and keep the ordered menu item as the hero",
    "Place the food in the lower third of the frame, not vertically centered",
    "Keep the visual mass center of the food below 60% of the frame height",
    "Do not add extra food",
    _HF_EXCLUDE_TABLE_CLUTTER,
)

_HF_POSTER_BG_BASE = _sentence(
    "Replace the background with a flat solid-color commercial poster backdrop",
    "Use clean graphic design rather than a photographed cafe interior",
    "Keep a simple top-to-bottom color flow with no interior scene",
)


# =============================================================================
# 1. Studio
# =============================================================================

_HF_STUDIO_INSTRUCTION_TEMPLATE = """
Edit the reference photo of {food_type_label} into a polished studio commercial food image.

{user_priority_block}Food preservation: {food_subject_rules}

Scene changes: {studio_scene_rules}

Quality: {realism_rules}

Make the food slightly more appetizing through lighting, background, and composition only. Do not change the food shape, portions, vessel, layering, or color away from the reference.

The image must contain no readable text, numbers, labels, logos, or watermarks.
Tone: {tone}.
""".strip()

_HF_STUDIO_SOUP_STEW_SUBJECT = _sentence(
    _HF_STUDIO_FOOD_BASE,
    "Keep the main pot and any side dishes that belong to the dish",
    "Preserve natural broth color",
)

_HF_STUDIO_FRIED_SUBJECT = _sentence(
    _HF_STUDIO_FOOD_BASE,
    "Keep a natural golden crust without a greasy or over-fried look",
)

_HF_STUDIO_GRILLED_BBQ_SUBJECT = _sentence(
    _HF_STUDIO_FOOD_BASE,
    "Preserve natural grill marks and sear without heavy smoke",
)

_HF_STUDIO_RICE_DISH_SUBJECT = _sentence(
    _HF_STUDIO_FOOD_BASE,
    "Keep rice, noodle, and topping layers visible with natural colors",
)

_HF_STUDIO_BREAD_DESSERT_SUBJECT = _sentence(
    _HF_STUDIO_FOOD_BASE,
    "Preserve natural crumb, cream, and layer texture",
)

_HF_STUDIO_BURGER_SANDWICH_SUBJECT = _sentence(
    _HF_STUDIO_FOOD_BASE,
    "Keep bun, patty, vegetable, and sauce layers natural and not collapsed",
)

_HF_STUDIO_COFFEE_DRINK_SUBJECT = _sentence(
    _HF_STUDIO_FOOD_BASE,
    "Preserve the cup shape and drink layers exactly as in the photo",
    "Do not add foam or toppings that are not in the original",
)

_HF_STUDIO_SOUP_STEW_SCENE = _sentence(
    _HF_STUDIO_SCENE_BASE,
    "Use a warm wood-tone table and soft warm light",
)

_HF_STUDIO_FRIED_SCENE = _sentence(
    _HF_STUDIO_SCENE_BASE,
    "Use a warm neutral table and soft side light",
)

_HF_STUDIO_GRILLED_BBQ_SCENE = _sentence(
    _HF_STUDIO_SCENE_BASE,
    "Use a dark warm table tone, soft side light, and natural contrast",
)

_HF_STUDIO_RICE_DISH_SCENE = _sentence(
    _HF_STUDIO_SCENE_BASE,
    "Use a bright clean table, soft even light, and keep the full bowl in frame",
)

_HF_STUDIO_BREAD_DESSERT_SCENE = _sentence(
    _HF_STUDIO_SCENE_BASE,
    "Use a bright cafe-style table and soft diffused light with the full dessert in frame",
)

_HF_STUDIO_BURGER_SANDWICH_SCENE = _sentence(
    _HF_STUDIO_SCENE_BASE,
    "Use a casual dining table, soft side light, and keep the full sandwich in frame",
)

_HF_STUDIO_COFFEE_DRINK_SCENE = _sentence(
    _HF_STUDIO_SCENE_BASE,
    "Use a clean cafe table, soft natural window light, and keep the full cup in frame",
)

HF_FOOD_STUDIO_SUBJECT_RULES: dict[FoodType, str] = {
    "soup_stew": _HF_STUDIO_SOUP_STEW_SUBJECT,
    "fried": _HF_STUDIO_FRIED_SUBJECT,
    "grilled_bbq": _HF_STUDIO_GRILLED_BBQ_SUBJECT,
    "rice_dish": _HF_STUDIO_RICE_DISH_SUBJECT,
    "bread_dessert": _HF_STUDIO_BREAD_DESSERT_SUBJECT,
    "burger_sandwich": _HF_STUDIO_BURGER_SANDWICH_SUBJECT,
    "coffee_drink": _HF_STUDIO_COFFEE_DRINK_SUBJECT,
}

HF_FOOD_STUDIO_SCENE_RULES: dict[FoodType, str] = {
    "soup_stew": _HF_STUDIO_SOUP_STEW_SCENE,
    "fried": _HF_STUDIO_FRIED_SCENE,
    "grilled_bbq": _HF_STUDIO_GRILLED_BBQ_SCENE,
    "rice_dish": _HF_STUDIO_RICE_DISH_SCENE,
    "bread_dessert": _HF_STUDIO_BREAD_DESSERT_SCENE,
    "burger_sandwich": _HF_STUDIO_BURGER_SANDWICH_SCENE,
    "coffee_drink": _HF_STUDIO_COFFEE_DRINK_SCENE,
}

_HF_STUDIO_TEMPLATE = _HF_STUDIO_INSTRUCTION_TEMPLATE


# =============================================================================
# 2. Poster
# =============================================================================

HF_POSTER_LAYOUT_RULES = _sentence(
    "Use a 2:3 portrait layout with a quiet designed background in the upper 38-44% for later headline overlay",
    "Anchor the food hero in the lower half with the vertical center of the food below 62% of the frame height",
    "Never center the food vertically",
    "Place the food base near the bottom 10-15% margin on a simple surface",
    "Keep the top-left and upper-center calm for later typography",
    "Keep the bottom 8% calm for a later full-width store footer while continuing the same background naturally",
    "Do not add a footer panel, color band, or hard horizontal split",
    "{store_footer_line}",
)

_HF_POSTER_INSTRUCTION_TEMPLATE = """
Edit the reference photo of {food_type_label} into a menu promotion poster image with food and designed background only.

{user_priority_block}Layout: {poster_layout_rules}

Food: {poster_food_rules}

Background: {poster_background_rules}

Quality: {realism_rules}

Preserve the food shape and vessel from the reference. Redesign only the background, lighting, and composition. Do not add any typography in the image pixels.

The image must contain no readable text, numbers, labels, logos, or watermarks.
Tone: {tone}.
""".strip()

_HF_POSTER_SOUP_STEW_FOOD = _sentence(
    _HF_POSTER_FOOD_BASE,
    "Show the main pot only without side plates",
    "Keep glossy broth and a moderate hero scale, not an oversized close-up",
    "Let the pot or bowl occupy about 32-42% of frame height and at most 50-58% of frame width",
    "Leave visible empty background margin around the vessel on all sides",
    "Place the tall pot or bowl base near the bottom edge with the rim below the vertical midpoint",
)

_HF_POSTER_FRIED_FOOD = _sentence(
    _HF_POSTER_FOOD_BASE,
    "Keep crispy golden fried texture without a soggy look",
)

_HF_POSTER_GRILLED_BBQ_FOOD = _sentence(
    _HF_POSTER_FOOD_BASE,
    "Preserve grill marks, sear gloss, and char texture",
)

_HF_POSTER_RICE_DISH_FOOD = _sentence(
    _HF_POSTER_FOOD_BASE,
    "Keep rice, noodle, and topping layers clearly visible",
)

_HF_POSTER_BREAD_DESSERT_FOOD = _sentence(
    _HF_POSTER_FOOD_BASE,
    "Preserve crumb, cream, and topping detail",
)

_HF_POSTER_BURGER_SANDWICH_FOOD = _sentence(
    _HF_POSTER_FOOD_BASE,
    "Keep bun, patty, cheese, and sauce layers appetizing and readable",
)

_HF_POSTER_COFFEE_DRINK_FOOD = _sentence(
    _HF_POSTER_FOOD_BASE,
    "Preserve cup shape and foam, ice, or beverage layers clearly",
    "Do not add a straw, stirrer, or drinking accessories",
    "Keep the open cup rim visible",
)

_HF_POSTER_SOUP_STEW_BACKGROUND = _sentence(
    _HF_POSTER_BG_BASE,
    "Use a warm cream-to-terracotta solid gradient with an appetizing hot-meal mood",
)

_HF_POSTER_FRIED_BACKGROUND = _sentence(
    _HF_POSTER_BG_BASE,
    "Use a warm orange-to-gold solid gradient with a bright appetizing tone",
)

_HF_POSTER_GRILLED_BBQ_BACKGROUND = _sentence(
    _HF_POSTER_BG_BASE,
    "Use a deep charcoal-to-brown solid gradient with premium contrast",
)

_HF_POSTER_RICE_DISH_BACKGROUND = _sentence(
    _HF_POSTER_BG_BASE,
    "Use a light beige-to-warm ivory solid gradient for a clean meal promo",
)

_HF_POSTER_BREAD_DESSERT_BACKGROUND = _sentence(
    _HF_POSTER_BG_BASE,
    "Use a pastel cream-to-latte solid gradient for a soft dessert promo",
)

_HF_POSTER_BURGER_SANDWICH_BACKGROUND = _sentence(
    _HF_POSTER_BG_BASE,
    "Use a warm red-to-mustard solid gradient for a bold casual promo",
)

_HF_POSTER_COFFEE_DRINK_BACKGROUND = _sentence(
    _HF_POSTER_BG_BASE,
    "Use a soft white-to-matcha green solid gradient for a minimal drink promo",
)

HF_FOOD_POSTER_FOOD_RULES: dict[FoodType, str] = {
    "soup_stew": _HF_POSTER_SOUP_STEW_FOOD,
    "fried": _HF_POSTER_FRIED_FOOD,
    "grilled_bbq": _HF_POSTER_GRILLED_BBQ_FOOD,
    "rice_dish": _HF_POSTER_RICE_DISH_FOOD,
    "bread_dessert": _HF_POSTER_BREAD_DESSERT_FOOD,
    "burger_sandwich": _HF_POSTER_BURGER_SANDWICH_FOOD,
    "coffee_drink": _HF_POSTER_COFFEE_DRINK_FOOD,
}

HF_FOOD_POSTER_BACKGROUND_RULES: dict[FoodType, str] = {
    "soup_stew": _HF_POSTER_SOUP_STEW_BACKGROUND,
    "fried": _HF_POSTER_FRIED_BACKGROUND,
    "grilled_bbq": _HF_POSTER_GRILLED_BBQ_BACKGROUND,
    "rice_dish": _HF_POSTER_RICE_DISH_BACKGROUND,
    "bread_dessert": _HF_POSTER_BREAD_DESSERT_BACKGROUND,
    "burger_sandwich": _HF_POSTER_BURGER_SANDWICH_BACKGROUND,
    "coffee_drink": _HF_POSTER_COFFEE_DRINK_BACKGROUND,
}

_HF_POSTER_TEMPLATE = _HF_POSTER_INSTRUCTION_TEMPLATE


# =============================================================================
# 3. Reels (instagram_feed)
# =============================================================================

HF_REELS_FOOD_RULES = _sentence(
    _HF_SUBJECT_HERO_COMMON,
    "Use an extreme close-up so the main dish fills about 70-85% of the frame",
    "Keep side items only at the edges if needed",
)

HF_REELS_SCENE_RULES = _sentence(
    "Preserve the original restaurant or store interior, table decor, lighting, and signage from the reference",
    "Shallow background blur is acceptable",
    "Do not replace the scene with a studio table or solid-color backdrop",
    "Make it look like a bright, sharp, appetizing smartphone restaurant reels thumbnail",
    "Use a 45-degree or slight top-down angle",
    "Do not include people",
    "Leave the bottom-left 20% relatively empty for later text overlay",
)

HF_REELS_SCENE_RULES_FLEXIBLE = _sentence(
    "Preserve the restaurant or store interior from the reference photo",
    "The user may adjust lighting, mood, color, or table styling only within the same in-store location",
    "Do not replace the background with a studio or solid-color backdrop",
    "Use an extreme close-up with the main dish filling about 70-85% of the frame",
    "Do not include people",
    "Leave the bottom-left 20% relatively empty for later text overlay",
)

HF_REELS_REALISM_EXTRA = _sentence(
    "Keep an authentic in-store smartphone single-shot look rather than a studio reshoot or composite",
    "Food and background must remain from the same location and shoot",
    "Do not add fake bokeh, over-sharpening, or a CGI advertisement look",
)

_HF_REELS_INSTRUCTION_TEMPLATE = """
Edit the reference in-store photo of {food_type_label} into a social media reels food thumbnail.

{user_priority_block}Food: {reels_food_rules}

Scene: {reels_scene_rules}

Quality: {realism_rules}. {reels_realism_extra}

Keep the food appearance and store interior faithful to the reference. Make the food slightly more appetizing without changing what the dish is.

Do not add hook text, captions, prices, store labels, or any readable text in the image pixels.
Tone: {tone}.
""".strip()

_HF_REELS_TEMPLATE = _HF_REELS_INSTRUCTION_TEMPLATE


def _poster_food_rules_with_menu(
    base_rules: str,
    *,
    menu_name: str,
    variant: ImageVariantType,
) -> str:
    if variant != "poster":
        return base_rules
    menu = (menu_name or "").strip()
    if not menu:
        return base_rules
    return _sentence(base_rules, f"The image must clearly depict the menu item: {menu}")


def _build_hf_reels_scene_rules(extra_notes: str) -> str:
    if openai_prompts._user_requests_visual_override(extra_notes):  # noqa: SLF001
        return _require_hf(HF_REELS_SCENE_RULES_FLEXIBLE, "HF_REELS_SCENE_RULES_FLEXIBLE")
    return _require_hf(HF_REELS_SCENE_RULES, "HF_REELS_SCENE_RULES")


def _lookup_hf_food_rules(
    registry: dict[FoodType, str],
    food_type: FoodType,
    *,
    registry_name: str,
) -> str:
    return _require_hf(registry.get(food_type), f"{registry_name}[{food_type!r}]")


def _format_user_priority_block(extra_notes: str) -> str:
    block = openai_prompts._build_user_priority_block(extra_notes)  # noqa: SLF001
    if not block.strip():
        return ""
    return f"User request: {block.strip()}\n\n"


# =============================================================================
# 4. Template registry
# =============================================================================

HF_FOOD_VARIANT_PROMPT_TEMPLATES: dict[tuple[FoodType, ImageVariantType], str] = {
    **{
        (food_type, "studio"): _HF_STUDIO_TEMPLATE
        for food_type in HF_FOOD_STUDIO_SUBJECT_RULES
    },
    **{
        (food_type, "poster"): _HF_POSTER_TEMPLATE
        for food_type in HF_FOOD_STUDIO_SUBJECT_RULES
    },
    **{
        (food_type, "instagram_feed"): _HF_REELS_TEMPLATE
        for food_type in HF_FOOD_STUDIO_SUBJECT_RULES
    },
}


# =============================================================================
# Public API
# =============================================================================


def uses_hf_custom_template(food_type: FoodType, variant: ImageVariantType) -> bool:
    template = HF_FOOD_VARIANT_PROMPT_TEMPLATES.get((food_type, variant), "").strip()
    return bool(template)


def build_hf_template_context(
    payload: ImageAdRequest,
    *,
    food_type: FoodType,
    variant: ImageVariantType,
) -> dict[str, str]:
    store_name = payload.store_name or ""
    store_location = (payload.store_location or "").strip()
    headline = (payload.headline or "").strip()
    if not headline and variant == "poster":
        headline = resolve_poster_headline(
            payload.promotion_goal or "",
            payload.tone,
        )
    price_text = (payload.price_text or "").strip()
    extra_notes = (payload.extra_notes or "").strip()
    price_line, price_accuracy_line = openai_prompts._build_poster_price_lines(price_text)  # noqa: SLF001
    menu_name = payload.menu_name or "오늘의 메뉴"

    poster_food = _poster_food_rules_with_menu(
        _lookup_hf_food_rules(
            HF_FOOD_POSTER_FOOD_RULES,
            food_type,
            registry_name="HF_FOOD_POSTER_FOOD_RULES",
        ),
        menu_name=menu_name,
        variant=variant,
    )

    return {
        "store_name": store_name,
        "store_location": store_location,
        "menu_name": menu_name,
        "tone": payload.tone or "",
        "promotion_goal": payload.promotion_goal or "",
        "extra_notes": extra_notes,
        "user_priority_block": _format_user_priority_block(extra_notes),
        "food_type_label": FOOD_TYPE_LABELS[food_type],
        "variant_label": VARIANT_LABELS[variant],
        "scene_hint": FOOD_TYPE_SCENE_HINTS[food_type],
        "variant_hint": VARIANT_DIRECTION_HINTS[variant],
        "headline_line": openai_prompts._build_poster_headline_line(  # noqa: SLF001
            headline=headline,
            store_name=store_name,
        ),
        "price_line": price_line,
        "price_accuracy_line": price_accuracy_line,
        "extra_notes_line": "",
        "food_subject_rules": _lookup_hf_food_rules(
            HF_FOOD_STUDIO_SUBJECT_RULES,
            food_type,
            registry_name="HF_FOOD_STUDIO_SUBJECT_RULES",
        ),
        "studio_scene_rules": _lookup_hf_food_rules(
            HF_FOOD_STUDIO_SCENE_RULES,
            food_type,
            registry_name="HF_FOOD_STUDIO_SCENE_RULES",
        ),
        "poster_food_rules": poster_food,
        "poster_background_rules": _lookup_hf_food_rules(
            HF_FOOD_POSTER_BACKGROUND_RULES,
            food_type,
            registry_name="HF_FOOD_POSTER_BACKGROUND_RULES",
        ),
        "poster_layout_rules": _require_hf(HF_POSTER_LAYOUT_RULES, "HF_POSTER_LAYOUT_RULES").format(
            store_footer_line=openai_prompts._build_poster_store_footer_line(  # noqa: SLF001
                store_name,
                store_location,
            ),
        ),
        "reels_food_rules": _require_hf(HF_REELS_FOOD_RULES, "HF_REELS_FOOD_RULES"),
        "reels_scene_rules": _build_hf_reels_scene_rules(extra_notes),
        "reels_realism_extra": _require_hf(HF_REELS_REALISM_EXTRA, "HF_REELS_REALISM_EXTRA"),
        "reels_hook_line": openai_prompts._build_reels_hook_line(  # noqa: SLF001
            store_name=store_name,
            menu_name=payload.menu_name or "",
            store_location=store_location,
            promotion_goal=payload.promotion_goal or "",
            price_text=price_text,
        ),
        "realism_rules": _require_hf(HF_REALISM_RULES, "HF_REALISM_RULES"),
    }


def render_hf_food_variant_prompt_template(
    payload: ImageAdRequest,
    *,
    food_type: FoodType,
    variant: ImageVariantType,
) -> str | None:
    template = HF_FOOD_VARIANT_PROMPT_TEMPLATES.get((food_type, variant), "").strip()
    if not template:
        return None

    context = build_hf_template_context(payload, food_type=food_type, variant=variant)
    return "\n".join(
        line.rstrip()
        for line in template.format(**context).splitlines()
        if line.strip()
    )


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
    if variant == "poster":
        return _require_hf(HF_NEGATIVE_POSTER, "HF_NEGATIVE_POSTER")
    if variant == "instagram_feed":
        return _require_hf(HF_NEGATIVE_REELS, "HF_NEGATIVE_REELS")
    if variant == "studio":
        return _require_hf(HF_NEGATIVE_STUDIO, "HF_NEGATIVE_STUDIO")
    return _require_hf(HF_NEGATIVE_COMMON, "HF_NEGATIVE_COMMON")


def strip_prompt_neg_line(prompt: str) -> str:
    """Legacy SDXL helper — Boogu prompts no longer embed NEG lines."""

    lines = [line for line in prompt.splitlines() if not line.strip().startswith("NEG:")]
    return "\n".join(lines).strip()
