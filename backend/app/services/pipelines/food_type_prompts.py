"""
Food-type × image-variant prompt templates (compact English keywords).

Read order:
    0. Global shared blocks (negative, realism, preserve)
    1. Studio — base + per food-type subject/scene tags
    2. Poster — layout + per food-type food/background tags
    3. Reels — shared across food types
    4. Template registry · public API

Preview:
    cd backend
    python scripts/preview_image_prompts.py --food-type fried --variant poster
"""

from __future__ import annotations

from typing import Callable

from app.schemas.food_type import FOOD_TYPE_LABELS, FoodType
from app.schemas.image_ad import ImageAdRequest, ImageVariantType
from app.utils.poster_taglines import resolve_poster_headline_from_purpose
from app.utils.reels_hooks import resolve_reels_hook_from_purpose

# =============================================================================
# Meta · fallback hints
# =============================================================================

VARIANT_LABELS: dict[ImageVariantType, str] = {
    "studio": "studio",
    "poster": "poster",
    "instagram_feed": "instagram reels",
}

FOOD_TYPE_SCENE_HINTS: dict[FoodType, str] = {
    "soup_stew": "soup/stew, walnut table editorial, keep main + side dishes",
    "fried": "fried food, crispy texture, golden crust, no greasy look",
    "grilled_bbq": "grilled BBQ, grill marks, char, warm dark mood",
    "rice_dish": "rice bowl/stir-fry/bibimbap, visible layers, color contrast",
    "bread_dessert": "bread/dessert/cake, crumb/cream detail, cafe mood",
    "burger_sandwich": "burger/sandwich, visible layers, fresh ingredients",
    "coffee_drink": "coffee/drink, cup shape, beverage layers, clean commercial shot",
}

VARIANT_DIRECTION_HINTS: dict[ImageVariantType, str] = {
    "studio": "medium wide editorial food photo, table+background visible, no extreme closeup",
    "poster": "4:5 menu promo poster, designed top bg + food hero bottom, PIL text overlay",
    "instagram_feed": "reels mood, preserve store bg, extreme food closeup",
}

# =============================================================================
# 0. Global shared keyword blocks
# =============================================================================

# QUALITY line — photoreal look (all variants). Anti-fake rendering lives here only.
_REALISM_RULES = (
    "real camera editorial food photo, natural texture/gloss/grain, steam if hot, "
    "no CGI/plastic/HDR/neon/beauty filter"
)

_NEGATIVE_COMMON = (
    "no text, numbers, logo, watermark, UI, dish name, menu title, caption, subtitle in image"
)

_NEGATIVE_REELS = f"{_NEGATIVE_COMMON}, hook via PIL only"

_PRESERVE_FOOD_BASE = (
    "preserve original food/toppings/containers, no add/remove props, no floating/cropped vessels"
)

_STUDIO_SCENE_BASE = (
    "clear table clutter, medium wide 50mm, food 55-65% frame, 45deg, no people"
)

_POSTER_FOOD_BASE = "preserve original main dish, no added food"

_POSTER_BG_BASE = "designed commercial poster bg, cohesive top+bottom flow"

_VISUAL_OVERRIDE_KEYWORDS: tuple[str, ...] = (
    # Korean
    "배경",
    "테이블",
    "조명",
    "분위기",
    "색감",
    "톤",
    "연출",
    "느낌",
    "스타일",
    "밝",
    "어둡",
    "따뜻",
    "차분",
    "미니멀",
    "나무",
    "우드",
    "베이지",
    # English
    "background",
    "table",
    "lighting",
    "mood",
    "tone",
    "color",
    "style",
    "bright",
    "dark",
    "warm",
    "minimal",
    "wood",
)


def _user_requests_visual_override(extra_notes: str) -> bool:
    text = (extra_notes or "").strip().lower()
    if not text:
        return False
    return any(keyword in text for keyword in _VISUAL_OVERRIDE_KEYWORDS)


def _build_user_priority_block(extra_notes: str) -> str:
    note = (extra_notes or "").strip()
    if not note:
        return ""

    return f"PRIORITY: {note}. Keep SUBJECT rules."


# =============================================================================
# 1. Studio
# =============================================================================

_STUDIO_PHOTO_TEMPLATE = """
TASK: editorial food reshoot from attached photo
TYPE: {food_type_label}
{user_priority_block}SUBJECT: {food_subject_rules}
SCENE: {studio_scene_rules}
QUALITY: {realism_rules}
GOAL: {promotion_goal}, TONE: {tone}
NEG: {_NEGATIVE_COMMON}
""".strip()

# --- studio subject tags per food type ---

_STUDIO_SOUP_STEW_SUBJECT = (
    f"{_PRESERVE_FOOD_BASE}, keep main pot + all side dish plates, "
    "vivid broth, tofu/kimchi/pottery detail"
)

_STUDIO_FRIED_SUBJECT = (
    f"{_PRESERVE_FOOD_BASE}, crispy golden crust, sharp fry texture, not soggy/oily"
)

_STUDIO_GRILLED_BBQ_SUBJECT = (
    f"{_PRESERVE_FOOD_BASE}, grill marks, sear gloss, juicy meat surface, "
    "natural plate smoke not CG smoke"
)

_STUDIO_RICE_DISH_SUBJECT = (
    f"{_PRESERVE_FOOD_BASE}, visible rice/noodle+topping layers, strong color contrast"
)

_STUDIO_BREAD_DESSERT_SUBJECT = (
    f"{_PRESERVE_FOOD_BASE}, crisp crumb, cream/glaze/layer detail"
)

_STUDIO_BURGER_SANDWICH_SUBJECT = (
    f"{_PRESERVE_FOOD_BASE}, visible bun/patty/veg/sauce layers, not collapsed/soggy"
)

_STUDIO_COFFEE_DRINK_SUBJECT = (
    f"{_PRESERVE_FOOD_BASE}, cup condensation, beverage layers, foam/cream texture"
)

# --- studio scene tags per food type ---

_STUDIO_SOUP_STEW_SCENE = (
    f"{_STUDIO_SCENE_BASE}, walnut/dark oak wood table, warm brown bokeh wood-wall bg, "
    "warm side light, table 35-45% frame, no crushed blacks"
)

_STUDIO_FRIED_SCENE = (
    f"{_STUDIO_SCENE_BASE}, rough wood board or craft paper, warm side light, "
    "highlight crispy surface gloss"
)

_STUDIO_GRILLED_BBQ_SCENE = (
    f"{_STUDIO_SCENE_BASE}, cast iron grill pan, dark warm charcoal/brown bokeh, "
    "strong side light, meat+grill in frame, red/brown contrast"
)

_STUDIO_RICE_DISH_SCENE = (
    f"{_STUDIO_SCENE_BASE}, bright cream/light gray seamless bg, soft even studio light, "
    "top-down or slight angle, full bowl in frame"
)

_STUDIO_BREAD_DESSERT_SCENE = (
    f"{_STUDIO_SCENE_BASE}, bright marble or linen cloth, soft window/diffused light, "
    "45deg side angle, full dessert in frame"
)

_STUDIO_BURGER_SANDWICH_SCENE = (
    f"{_STUDIO_SCENE_BASE}, craft paper or slate board, warm side light, "
    "eye-level front/side angle, layer cross-section visible"
)

_STUDIO_COFFEE_DRINK_SCENE = (
    f"{_STUDIO_SCENE_BASE}, bright oak or white table, soft diffused window light, "
    "center front/slight side, full cup in frame"
)

FOOD_STUDIO_SUBJECT_RULES: dict[FoodType, str] = {
    "soup_stew": _STUDIO_SOUP_STEW_SUBJECT,
    "fried": _STUDIO_FRIED_SUBJECT,
    "grilled_bbq": _STUDIO_GRILLED_BBQ_SUBJECT,
    "rice_dish": _STUDIO_RICE_DISH_SUBJECT,
    "bread_dessert": _STUDIO_BREAD_DESSERT_SUBJECT,
    "burger_sandwich": _STUDIO_BURGER_SANDWICH_SUBJECT,
    "coffee_drink": _STUDIO_COFFEE_DRINK_SUBJECT,
}

FOOD_STUDIO_SCENE_RULES: dict[FoodType, str] = {
    "soup_stew": _STUDIO_SOUP_STEW_SCENE,
    "fried": _STUDIO_FRIED_SCENE,
    "grilled_bbq": _STUDIO_GRILLED_BBQ_SCENE,
    "rice_dish": _STUDIO_RICE_DISH_SCENE,
    "bread_dessert": _STUDIO_BREAD_DESSERT_SCENE,
    "burger_sandwich": _STUDIO_BURGER_SANDWICH_SCENE,
    "coffee_drink": _STUDIO_COFFEE_DRINK_SCENE,
}

_STUDIO_TEMPLATE = _STUDIO_PHOTO_TEMPLATE.replace("{_NEGATIVE_COMMON}", _NEGATIVE_COMMON)


# =============================================================================
# 2. Poster
# =============================================================================

_POSTER_LAYOUT_RULES = (
    "LAYOUT 4:5 1024x1536, top 38% empty designed bg (PIL text), bottom 55-60% food hero, "
    "top-right price-pill space, bottom-right store space. {store_footer_line}"
)

_POSTER_PHOTO_TEMPLATE = """
TASK: menu promo poster from attached food photo
TYPE: {food_type_label}
{user_priority_block}{poster_layout_rules}
SUBJECT: {poster_food_rules}
BG: {poster_background_rules}
QUALITY: {realism_rules}
GOAL: {promotion_goal}, TONE: {tone}
NEG: {_NEGATIVE_COMMON}, no flat-only bg, no brand copy
""".strip()

# --- poster food tags ---

_POSTER_SOUP_STEW_FOOD = (
    f"{_POSTER_FOOD_BASE}, main pot only no side plates, glossy broth"
)

_POSTER_FRIED_FOOD = (
    f"{_POSTER_FOOD_BASE}, crispy golden fried chicken/crust, not soggy"
)

_POSTER_GRILLED_BBQ_FOOD = (
    f"{_POSTER_FOOD_BASE}, grill marks, sear gloss, char texture"
)

_POSTER_RICE_DISH_FOOD = (
    f"{_POSTER_FOOD_BASE}, rice/noodle+topping layers visible"
)

_POSTER_BREAD_DESSERT_FOOD = (
    f"{_POSTER_FOOD_BASE}, crumb/cream/topping detail"
)

_POSTER_BURGER_SANDWICH_FOOD = (
    f"{_POSTER_FOOD_BASE}, bun/patty/cheese/sauce layers appetizing"
)

_POSTER_COFFEE_DRINK_FOOD = (
    f"{_POSTER_FOOD_BASE}, cup shape, foam/ice/beverage layers clear"
)

# --- poster background tags ---

_POSTER_SOUP_STEW_BACKGROUND = (
    f"{_POSTER_BG_BASE}, warm wood/stone/hanji texture, subtle traditional pattern, "
    "warm cream/terracotta/deep brown, hot-steam mood"
)

_POSTER_FRIED_BACKGROUND = (
    f"{_POSTER_BG_BASE}, casual dining poster, craft paper/wood, warm orange/gold pattern, "
    "bright appetizing tone"
)

_POSTER_GRILLED_BBQ_BACKGROUND = (
    f"{_POSTER_BG_BASE}, dark BBQ poster, charcoal/smoke/deep brown pattern, premium contrast"
)

_POSTER_RICE_DISH_BACKGROUND = (
    f"{_POSTER_BG_BASE}, bright clean meal poster, wood/light beige soft pattern, warm tone"
)

_POSTER_BREAD_DESSERT_BACKGROUND = (
    f"{_POSTER_BG_BASE}, cafe dessert poster, pastel/cream/latte beige soft pattern"
)

_POSTER_BURGER_SANDWICH_BACKGROUND = (
    f"{_POSTER_BG_BASE}, casual diner/brunch poster, bold color/modern pattern, warm red/mustard accent"
)

_POSTER_COFFEE_DRINK_BACKGROUND = (
    f"{_POSTER_BG_BASE}, minimal cafe drink poster, white/oak/soft green clean pattern"
)

FOOD_POSTER_FOOD_RULES: dict[FoodType, str] = {
    "soup_stew": _POSTER_SOUP_STEW_FOOD,
    "fried": _POSTER_FRIED_FOOD,
    "grilled_bbq": _POSTER_GRILLED_BBQ_FOOD,
    "rice_dish": _POSTER_RICE_DISH_FOOD,
    "bread_dessert": _POSTER_BREAD_DESSERT_FOOD,
    "burger_sandwich": _POSTER_BURGER_SANDWICH_FOOD,
    "coffee_drink": _POSTER_COFFEE_DRINK_FOOD,
}

FOOD_POSTER_BACKGROUND_RULES: dict[FoodType, str] = {
    "soup_stew": _POSTER_SOUP_STEW_BACKGROUND,
    "fried": _POSTER_FRIED_BACKGROUND,
    "grilled_bbq": _POSTER_GRILLED_BBQ_BACKGROUND,
    "rice_dish": _POSTER_RICE_DISH_BACKGROUND,
    "bread_dessert": _POSTER_BREAD_DESSERT_BACKGROUND,
    "burger_sandwich": _POSTER_BURGER_SANDWICH_BACKGROUND,
    "coffee_drink": _POSTER_COFFEE_DRINK_BACKGROUND,
}

_POSTER_TEMPLATE = _POSTER_PHOTO_TEMPLATE.replace("{_NEGATIVE_COMMON}", _NEGATIVE_COMMON)


# =============================================================================
# 3. Reels (instagram_feed)
# =============================================================================

_REELS_FOOD_RULES = (
    f"{_PRESERVE_FOOD_BASE}, extreme closeup 70-85%, main dominant, sides at edges only"
)

_REELS_SCENE_RULES = (
    "keep original store interior/bg/lighting, shallow natural bokeh, no studio/solid bg swap, "
    "smartphone in-store single shot, 45deg or slight top-down, no people, bottom-left 20% empty"
)

_REELS_SCENE_RULES_FLEXIBLE = (
    "user may override bg/lighting/mood/color/table, no people, bottom-left 20% empty"
)

_REELS_PHOTO_TEMPLATE = """
TASK: reels food thumbnail from in-store photo
TYPE: {food_type_label}
{user_priority_block}SUBJECT: {reels_food_rules}
SCENE: {reels_scene_rules}
QUALITY: {realism_rules}
GOAL: {promotion_goal}, TONE: {tone}
NEG: {_NEGATIVE_REELS}
""".strip()

_REELS_TEMPLATE = _REELS_PHOTO_TEMPLATE.replace("{_NEGATIVE_REELS}", _NEGATIVE_REELS)


def _build_reels_scene_rules(extra_notes: str) -> str:
    if _user_requests_visual_override(extra_notes):
        return _REELS_SCENE_RULES_FLEXIBLE
    return _REELS_SCENE_RULES


# =============================================================================
# 4. Template registry
# =============================================================================

FOOD_VARIANT_PROMPT_TEMPLATES: dict[tuple[FoodType, ImageVariantType], str] = {
    **{(food_type, "studio"): _STUDIO_TEMPLATE for food_type in FOOD_STUDIO_SUBJECT_RULES},
    **{(food_type, "poster"): _POSTER_TEMPLATE for food_type in FOOD_STUDIO_SUBJECT_RULES},
    **{
        (food_type, "instagram_feed"): _REELS_TEMPLATE
        for food_type in FOOD_STUDIO_SUBJECT_RULES
    },
}


# =============================================================================
# Public API
# =============================================================================


def _build_reels_hook_line(
    *,
    store_name: str,
    menu_name: str,
    store_location: str = "",
    promotion_goal: str,
    price_text: str = "",
) -> str:
    hook = resolve_reels_hook_from_purpose(
        promotion_goal,
        store_name=store_name,
        menu_name=menu_name,
        store_location=store_location,
        price_text=price_text,
    )
    return f"PIL caption hook (not in image): {hook}"


def build_poster_exact_text_block(
    *,
    headline: str,
    menu_name: str,
    price_text: str = "",
    store_name: str = "",
) -> str:
    """Legacy helper — poster text is applied via PIL, not in the image prompt."""

    menu = (menu_name or "").strip() or "오늘의 메뉴"
    items: list[str] = []
    index = 1

    head = (headline or "").strip()
    if head:
        items.append(f'{index}. "{head}" — headline (small)')
        index += 1

    items.append(f'{index}. "{menu}" — menu name (largest bold)')
    index += 1

    price = (price_text or "").strip()
    if price:
        items.append(f'{index}. "{price}" — price (badge)')
        index += 1

    store = (store_name or "").strip()
    if store:
        items.append(f'{index}. "{store}" — store name bottom-right (small)')

    numbered = "\n".join(items)
    return (
        "EXACT TEXT (PIL only, not for image model):\n"
        f"{numbered}"
    )


def _build_poster_headline_line(*, headline: str, store_name: str) -> str:
    _ = store_name
    if headline:
        return f"PIL headline: {headline}"
    return ""


def _build_poster_price_lines(price_text: str) -> tuple[str, str]:
    if price_text:
        return (
            f"PIL price badge: {price_text}",
            "match price symbols/spacing exactly in PIL overlay",
        )
    return ("no price in PIL", "")


def _build_poster_store_footer_line(
    store_name: str,
    store_location: str = "",
) -> str:
    parts: list[str] = []
    if (store_name or "").strip():
        parts.append("reserve bottom-right for PIL store")
    if (store_location or "").strip():
        parts.append(f"location context: {store_location.strip()}")
    return ", ".join(parts)


def _lookup_food_rules(registry: dict[FoodType, str], food_type: FoodType) -> str:
    return registry.get(food_type, "")


def uses_custom_template(food_type: FoodType, variant: ImageVariantType) -> bool:
    template = FOOD_VARIANT_PROMPT_TEMPLATES.get((food_type, variant), "").strip()
    return bool(template)


def get_food_type_scene_hint(food_type: FoodType) -> str:
    return FOOD_TYPE_SCENE_HINTS[food_type]


def get_variant_direction_hint(variant: ImageVariantType) -> str:
    return VARIANT_DIRECTION_HINTS[variant]


def build_template_context(
    payload: ImageAdRequest,
    *,
    food_type: FoodType,
    variant: ImageVariantType,
) -> dict[str, str]:
    store_name = payload.store_name or ""
    store_location = (payload.store_location or "").strip()
    headline = (payload.headline or "").strip()
    if not headline and variant == "poster":
        headline = resolve_poster_headline_from_purpose(payload.promotion_goal or "")
    price_text = (payload.price_text or "").strip()
    extra_notes = (payload.extra_notes or "").strip()
    price_line, price_accuracy_line = _build_poster_price_lines(price_text)
    menu_name = payload.menu_name or "오늘의 메뉴"

    user_priority_block = _build_user_priority_block(extra_notes)
    if user_priority_block:
        user_priority_block = user_priority_block + "\n"

    return {
        "store_name": store_name,
        "store_location": store_location,
        "menu_name": menu_name,
        "tone": payload.tone or "",
        "promotion_goal": payload.promotion_goal or "",
        "extra_notes": extra_notes,
        "user_priority_block": user_priority_block,
        "food_type_label": FOOD_TYPE_LABELS[food_type],
        "variant_label": VARIANT_LABELS[variant],
        "scene_hint": get_food_type_scene_hint(food_type),
        "variant_hint": get_variant_direction_hint(variant),
        "headline_line": _build_poster_headline_line(
            headline=headline,
            store_name=store_name,
        ),
        "price_line": price_line,
        "price_accuracy_line": price_accuracy_line,
        "extra_notes_line": "",
        "food_subject_rules": FOOD_STUDIO_SUBJECT_RULES[food_type],
        "studio_scene_rules": FOOD_STUDIO_SCENE_RULES[food_type],
        "poster_food_rules": _lookup_food_rules(FOOD_POSTER_FOOD_RULES, food_type),
        "poster_background_rules": _lookup_food_rules(
            FOOD_POSTER_BACKGROUND_RULES, food_type
        ),
        "poster_layout_rules": _POSTER_LAYOUT_RULES.format(
            store_footer_line=_build_poster_store_footer_line(
                store_name,
                store_location,
            ),
        ),
        "reels_food_rules": _REELS_FOOD_RULES,
        "reels_scene_rules": _build_reels_scene_rules(extra_notes),
        "reels_hook_line": _build_reels_hook_line(
            store_name=store_name,
            menu_name=payload.menu_name or "",
            store_location=store_location,
            promotion_goal=payload.promotion_goal or "",
            price_text=price_text,
        ),
        "realism_rules": _REALISM_RULES,
    }


def render_food_variant_prompt_template(
    payload: ImageAdRequest,
    *,
    food_type: FoodType,
    variant: ImageVariantType,
) -> str | None:
    template = FOOD_VARIANT_PROMPT_TEMPLATES.get((food_type, variant), "").strip()
    if not template:
        return None

    context = build_template_context(payload, food_type=food_type, variant=variant)
    return template.format(**context)


def build_food_context_line(food_type: FoodType) -> str:
    label = FOOD_TYPE_LABELS[food_type]
    scene_hint = get_food_type_scene_hint(food_type)
    return f"food type: {label}, {scene_hint}"


def build_variant_context_line(variant: ImageVariantType) -> str:
    return f"variant: {get_variant_direction_hint(variant)}"


def append_food_and_variant_context(
    base_prompt: str,
    *,
    food_type: FoodType,
    variant: ImageVariantType,
) -> str:
    return ", ".join(
        [
            base_prompt,
            build_food_context_line(food_type),
            build_variant_context_line(variant),
        ]
    )


def build_food_variant_prompt(
    payload: ImageAdRequest,
    variant: ImageVariantType,
    *,
    food_type: FoodType,
    build_poster_prompt: Callable[[ImageAdRequest, str], str],
) -> str:
    custom_prompt = render_food_variant_prompt_template(
        payload,
        food_type=food_type,
        variant=variant,
    )
    if custom_prompt:
        return custom_prompt

    from app.services.pipelines.image_variant_prompts import VARIANT_LAYOUT_MAP

    layout_type = VARIANT_LAYOUT_MAP[variant]
    base_prompt = build_poster_prompt(payload, layout_type)
    return append_food_and_variant_context(
        base_prompt,
        food_type=food_type,
        variant=variant,
    )


def build_inpaint_food_prompt(payload: ImageAdRequest, food_type: FoodType) -> str:
    return build_food_context_line(food_type)
