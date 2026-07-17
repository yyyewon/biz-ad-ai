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

from app.schemas.food_type import FOOD_TYPE_LABELS, FoodType
from app.schemas.image_ad import ImageAdRequest, ImageVariantType
from app.utils.poster_taglines import resolve_poster_headline
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
    "studio": "polish casual food photo into clean studio shot, faithful food, better light/bg",
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

_NEGATIVE_CLUTTER = (
    "no empty plate, no water cup, no water glass, no napkin, no call bell, "
    "no receipt, no extra unrelated cups or tableware"
)

_NEGATIVE_COMMON = (
    "no text, numbers, logo, watermark, UI, dish name, menu title, caption, subtitle in image, "
    f"{_NEGATIVE_CLUTTER}"
)

# Poster: model outputs food+bg only; copy/price/store added via PIL overlay
_NEGATIVE_POSTER = (
    "no text, letters, numbers, price, currency, Korean menu title, dish name, store label, "
    "English words STORE NAME MENU PRICE, location, address, logo, watermark, UI, "
    "caption, subtitle, price badge, pill badge, placeholder typography in image pixels, "
    "typography added in post-processing only, do not burn any words into image, "
    "no cafe interior, no dining room, no brick wall backdrop, no wood table photo, "
    "no decorative pattern texture in top text zone, "
    f"{_NEGATIVE_CLUTTER}"
)

_NEGATIVE_REELS = (
    f"{_NEGATIVE_COMMON}, hook/caption via PIL only, not in image pixels, "
    "no Korean/English letters, no menu title, no price, no store label in image"
)

# Studio: upgrade framing/light/bg but do not exaggerate the food itself
_NEGATIVE_STUDIO = (
    f"{_NEGATIVE_COMMON}, no exaggerated gloss/oil/smoke/steam, "
    "no added toppings/foam/cream/condensation, no oversaturated food colors, "
    "no Korean/English letters, no menu title, no price, no store label, no caption"
)

_PRESERVE_FOOD_BASE = (
    "preserve original main-menu food/toppings and its serving vessel, "
    "no add/remove food items, no floating/cropped vessels"
)

_EXCLUDE_TABLE_CLUTTER = (
    "remove empty plates, water cups/glasses, napkins, call bell, menus, "
    "unrelated drinks and table clutter"
)

_SUBJECT_HERO_COMMON = (
    f"{_PRESERVE_FOOD_BASE}, hero focus on ordered menu item, {_EXCLUDE_TABLE_CLUTTER}"
)

_STUDIO_SCENE_BASE = (
    "upgrade casual shot to clean studio food photo, tidy table, soft even professional light, "
    "uncluttered background, medium wide framing, food 55-65% frame, no people"
)

_STUDIO_FOOD_BASE = (
    f"{_PRESERVE_FOOD_BASE}, hero focus on ordered menu item, "
    f"keep food appearance faithful to attached photo, {_EXCLUDE_TABLE_CLUTTER}"
)

_POSTER_FOOD_BASE = (
    f"preserve original main dish, hero focus on ordered menu item, "
    f"no added food, {_EXCLUDE_TABLE_CLUTTER}"
)

_POSTER_BG_BASE = (
    "flat solid-color commercial poster background, clean graphic design not a cafe photo, "
    "simple top-to-bottom color flow, no interior scene"
)

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
TASK: polish attached casual food photo into a clean studio commercial shot
TYPE: {food_type_label}
{user_priority_block}SUBJECT: {food_subject_rules}
SCENE: {studio_scene_rules}
QUALITY: {realism_rules}
MOOD: appetizing commercial atmosphere, TONE: {tone}
CRITICAL: image pixels must have no readable text (Korean/English), no numbers, no labels
PRESERVE: keep food shape, portions, vessel, layering and color faithful to photo; improve only light/bg/composition
NEG: {_NEGATIVE_STUDIO}
""".strip()

# --- studio subject tags per food type ---

_STUDIO_SOUP_STEW_SUBJECT = (
    f"{_STUDIO_FOOD_BASE}, keep main pot + side dishes, natural broth color"
)

_STUDIO_FRIED_SUBJECT = (
    f"{_STUDIO_FOOD_BASE}, natural golden crust, not greasy or over-fried"
)

_STUDIO_GRILLED_BBQ_SUBJECT = (
    f"{_STUDIO_FOOD_BASE}, natural grill marks and sear, no heavy smoke"
)

_STUDIO_RICE_DISH_SUBJECT = (
    f"{_STUDIO_FOOD_BASE}, visible rice/noodle+topping layers, natural colors"
)

_STUDIO_BREAD_DESSERT_SUBJECT = (
    f"{_STUDIO_FOOD_BASE}, natural crumb/cream/layer texture"
)

_STUDIO_BURGER_SANDWICH_SUBJECT = (
    f"{_STUDIO_FOOD_BASE}, natural bun/patty/veg/sauce layers, not collapsed"
)

_STUDIO_COFFEE_DRINK_SUBJECT = (
    f"{_STUDIO_FOOD_BASE}, preserve cup shape and drink layers as in photo, "
    "no added foam/toppings not in original"
)

# --- studio scene tags per food type ---

_STUDIO_SOUP_STEW_SCENE = (
    f"{_STUDIO_SCENE_BASE}, warm wood-tone table, soft warm light"
)

_STUDIO_FRIED_SCENE = (
    f"{_STUDIO_SCENE_BASE}, warm neutral table, soft side light"
)

_STUDIO_GRILLED_BBQ_SCENE = (
    f"{_STUDIO_SCENE_BASE}, dark warm table tone, soft side light, natural contrast"
)

_STUDIO_RICE_DISH_SCENE = (
    f"{_STUDIO_SCENE_BASE}, bright clean table, soft even light, full bowl in frame"
)

_STUDIO_BREAD_DESSERT_SCENE = (
    f"{_STUDIO_SCENE_BASE}, bright cafe table, soft diffused light, full dessert in frame"
)

_STUDIO_BURGER_SANDWICH_SCENE = (
    f"{_STUDIO_SCENE_BASE}, casual dining table, soft side light, full sandwich in frame"
)

_STUDIO_COFFEE_DRINK_SCENE = (
    f"{_STUDIO_SCENE_BASE}, clean cafe table, soft natural window light, full cup in frame"
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

_STUDIO_TEMPLATE = _STUDIO_PHOTO_TEMPLATE.replace("{_NEGATIVE_STUDIO}", _NEGATIVE_STUDIO)


# =============================================================================
# 2. Poster
# =============================================================================

_POSTER_LAYOUT_RULES = (
    "LAYOUT 4:5 1024x1536, top 38% flat solid-color empty zone (no letters in image), "
    "bottom 55-60% food hero on simple surface, top-right empty patch, bottom-right empty corner. "
    "{store_footer_line}"
)

_POSTER_PHOTO_TEMPLATE = """
TASK: menu promo poster from attached food photo — food hero + designed background only, zero typography
TYPE: {food_type_label}
{user_priority_block}{poster_layout_rules}
SUBJECT: {poster_food_rules}
BG: {poster_background_rules}
QUALITY: {realism_rules}
MOOD: appetizing commercial promo atmosphere, TONE: {tone}
CRITICAL: image pixels must have no readable text (Korean/English), no numbers, no labels
PRESERVE: preserve food shape/vessel, redesign bg/lighting only, typography is post-process overlay not in image
NEG: {_NEGATIVE_POSTER}, no cafe interior, no restaurant room, no wood wall, no photo backdrop, no brand copy
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
    f"{_POSTER_BG_BASE}, warm cream-to-terracotta solid gradient, appetizing hot-meal mood"
)

_POSTER_FRIED_BACKGROUND = (
    f"{_POSTER_BG_BASE}, warm orange-to-gold solid gradient, bright appetizing tone"
)

_POSTER_GRILLED_BBQ_BACKGROUND = (
    f"{_POSTER_BG_BASE}, deep charcoal-to-brown solid gradient, premium contrast"
)

_POSTER_RICE_DISH_BACKGROUND = (
    f"{_POSTER_BG_BASE}, light beige-to-warm ivory solid gradient, clean meal promo"
)

_POSTER_BREAD_DESSERT_BACKGROUND = (
    f"{_POSTER_BG_BASE}, pastel cream-to-latte solid gradient, soft dessert promo"
)

_POSTER_BURGER_SANDWICH_BACKGROUND = (
    f"{_POSTER_BG_BASE}, warm red-to-mustard solid gradient, bold casual promo"
)

_POSTER_COFFEE_DRINK_BACKGROUND = (
    f"{_POSTER_BG_BASE}, soft white-to-matcha green solid gradient, minimal drink promo"
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

_POSTER_TEMPLATE = _POSTER_PHOTO_TEMPLATE.replace("{_NEGATIVE_POSTER}", _NEGATIVE_POSTER)


# =============================================================================
# 3. Reels (instagram_feed)
# =============================================================================

_REELS_FOOD_RULES = (
    f"{_SUBJECT_HERO_COMMON}, extreme closeup 70-85%, main dominant, sides at edges only"
)

_REELS_SCENE_RULES = (
    "preserve original restaurant/store interior, table decor, lighting, signage, "
    "shallow bokeh ok, no studio table/solid bg replacement, "
    "smartphone restaurant reels thumbnail, bright sharp appetizing, "
    "45deg or slight top-down, no people, bottom-left 20% empty for PIL"
)

_REELS_SCENE_RULES_FLEXIBLE = (
    "preserve restaurant/store interior from photo, user may adjust lighting/mood/color/table "
    "within same in-store location, no studio/solid bg replacement, extreme closeup 70-85%, "
    "no people, bottom-left 20% empty for PIL"
)

_REELS_REALISM_EXTRA = (
    "authentic in-store smartphone single shot, not studio reshoot/composite, "
    "food+bg same location same shoot, no fake bokeh/over-sharpen/CG ad look"
)

_REELS_PHOTO_TEMPLATE = """
TASK: reels food thumbnail from in-store photo — faithful food, zero typography
TYPE: {food_type_label}
{user_priority_block}SUBJECT: {reels_food_rules}
SCENE: {reels_scene_rules}
QUALITY: {realism_rules}, {reels_realism_extra}
MOOD: appetizing in-store atmosphere, TONE: {tone}
CRITICAL: image pixels must have no readable text (Korean/English), no numbers, no caption/hook text
PRESERVE: keep food appearance and store interior/bg faithful to photo; hook caption is PIL overlay only
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
    _ = (store_name, store_location)
    return "keep top and bottom-right corners blank, no typography in image"


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
        headline = resolve_poster_headline(
            payload.promotion_goal or "",
            payload.tone,
        )
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
        "reels_realism_extra": _REELS_REALISM_EXTRA,
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


def build_food_variant_prompt(
    payload: ImageAdRequest,
    variant: ImageVariantType,
    *,
    food_type: FoodType,
) -> str:
    custom_prompt = render_food_variant_prompt_template(
        payload,
        food_type=food_type,
        variant=variant,
    )
    if not custom_prompt:
        raise ValueError(
            f"No prompt template for food_type={food_type!r}, variant={variant!r}"
        )
    return custom_prompt


def build_variant_negative_prompt(variant: ImageVariantType) -> str:
    if variant == "poster":
        return _NEGATIVE_POSTER
    if variant == "instagram_feed":
        return _NEGATIVE_REELS
    if variant == "studio":
        return _NEGATIVE_STUDIO
    return _NEGATIVE_COMMON


def strip_prompt_neg_line(prompt: str) -> str:
    """HF negative_prompt 파라미터로 분리할 때 positive prompt에서 NEG 줄을 제거한다."""
    lines = [line for line in prompt.splitlines() if not line.strip().startswith("NEG:")]
    return "\n".join(lines).strip()


def build_inpaint_food_prompt(payload: ImageAdRequest, food_type: FoodType) -> str:
    return build_food_context_line(food_type)
