"""
HF image generation prompts (Stable Diffusion img2img / ControlNet).

OpenAI 경로: food_type_prompts.py
HF 경로: 이 파일만 수정한다. OpenAI fallback 없음 — 비어 있으면 즉시 오류.

Read order (food_type_prompts.py 와 동일 — 옆 파일과 줄 맞춰 보면 됨):
    Meta · hints
    0. Global shared blocks (negative, realism)
    1. Studio — template + per food-type subject/scene
    2. Poster — layout + per food-type food/background
    3. Reels (instagram_feed)
    4. Template registry
    Public API

편집 규칙:
    - OpenAI와 동일 상수명 패턴 (_HF_STUDIO_FRIED_SUBJECT ↔ _STUDIO_FRIED_SUBJECT)
    - 상수를 비우거나 None 으로 두면 생성 시 ValueError (조용히 OpenAI 로 넘어가지 않음)

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


# =============================================================================
# 0. Global shared keyword blocks
# =============================================================================
# ref openai: _REALISM_RULES, _NEGATIVE_*, _PRESERVE_FOOD_BASE, ...

HF_REALISM_RULES = (
    "real camera editorial food photo, natural texture/gloss/grain, steam if hot, "
    "no CGI/plastic/HDR/neon/beauty filter"
)

HF_NEGATIVE_CLUTTER = (
    "no empty plate, no water cup, no water glass, no napkin, no call bell, "
    "no receipt, no extra unrelated cups or tableware"
)

HF_NEGATIVE_COMMON = (
    "no text, numbers, logo, watermark, UI, dish name, menu title, caption, subtitle in image, "
    f"{HF_NEGATIVE_CLUTTER}"
)

HF_NEGATIVE_POSTER = (
    "no text, letters, numbers, price, currency, Korean menu title, dish name, store label, "
    "English words STORE NAME MENU PRICE, location, address, logo, watermark, UI, "
    "caption, subtitle, price badge, pill badge, placeholder typography in image pixels, "
    "typography added in post-processing only, do not burn any words into image, "
    "no cafe interior, no dining room, no brick wall backdrop, no wood table photo, "
    "no decorative pattern texture in top text zone, "
    "no vertically centered food hero, no food occupying upper 40% of frame, "
    "no oversized soup pot filling entire frame, no giant ttukbaegi closeup, "
    f"{HF_NEGATIVE_CLUTTER}"
)

HF_NEGATIVE_REELS = (
    f"{HF_NEGATIVE_COMMON}, hook/caption via PIL only, not in image pixels, "
    "no Korean/English letters, no menu title, no price, no store label in image"
)

HF_NEGATIVE_STUDIO = (
    f"{HF_NEGATIVE_COMMON}, no exaggerated gloss/oil/smoke/steam, "
    "no added toppings/foam/cream/condensation, no oversaturated food colors, "
    "no Korean/English letters, no menu title, no price, no store label, no caption"
)

_HF_PRESERVE_FOOD_BASE = (
    "preserve original main-menu food/toppings and its serving vessel, "
    "no add/remove food items, no floating/cropped vessels"
)

_HF_EXCLUDE_TABLE_CLUTTER = (
    "remove empty plates, water cups/glasses, napkins, call bell, menus, "
    "unrelated drinks and table clutter"
)

_HF_SUBJECT_HERO_COMMON = (
    f"{_HF_PRESERVE_FOOD_BASE}, hero focus on ordered menu item, {_HF_EXCLUDE_TABLE_CLUTTER}"
)

_HF_STUDIO_SCENE_BASE = (
    "upgrade casual shot to clean studio food photo, tidy table, soft even professional light, "
    "uncluttered background, medium wide framing, food 55-65% frame, no people"
)

_HF_STUDIO_FOOD_BASE = (
    f"{_HF_PRESERVE_FOOD_BASE}, hero focus on ordered menu item, "
    f"keep food appearance faithful to attached photo, {_HF_EXCLUDE_TABLE_CLUTTER}"
)

_HF_POSTER_FOOD_BASE = (
    f"preserve original main dish, hero focus on ordered menu item, "
    f"compose food in lower third of frame (not vertically centered), "
    f"food mass center below 60% frame height, "
    f"no added food, {_HF_EXCLUDE_TABLE_CLUTTER}"
)

_HF_POSTER_BG_BASE = (
    "flat solid-color commercial poster background, clean graphic design not a cafe photo, "
    "simple top-to-bottom color flow, no interior scene"
)


# =============================================================================
# 1. Studio
# =============================================================================

_HF_STUDIO_PHOTO_TEMPLATE = """
TASK: polish attached casual food photo into a clean studio commercial shot (HF img2img)
TYPE: {food_type_label}
{user_priority_block}SUBJECT: {food_subject_rules}
SCENE: {studio_scene_rules}
QUALITY: {realism_rules}
MOOD: appetizing commercial atmosphere, TONE: {tone}
CRITICAL: image pixels must have no readable text (Korean/English), no numbers, no labels
PRESERVE: keep food shape, portions, vessel, layering and color faithful to photo; improve only light/bg/composition
NEG: {hf_negative_studio}
""".strip()

# --- studio subject tags per food type ---
# ref openai: _STUDIO_*_SUBJECT

_HF_STUDIO_SOUP_STEW_SUBJECT = (
    f"{_HF_STUDIO_FOOD_BASE}, keep main pot + side dishes, natural broth color"
)

_HF_STUDIO_FRIED_SUBJECT = (
    f"{_HF_STUDIO_FOOD_BASE}, natural golden crust, not greasy or over-fried"
)

_HF_STUDIO_GRILLED_BBQ_SUBJECT = (
    f"{_HF_STUDIO_FOOD_BASE}, natural grill marks and sear, no heavy smoke"
)

_HF_STUDIO_RICE_DISH_SUBJECT = (
    f"{_HF_STUDIO_FOOD_BASE}, visible rice/noodle+topping layers, natural colors"
)

_HF_STUDIO_BREAD_DESSERT_SUBJECT = (
    f"{_HF_STUDIO_FOOD_BASE}, natural crumb/cream/layer texture"
)

_HF_STUDIO_BURGER_SANDWICH_SUBJECT = (
    f"{_HF_STUDIO_FOOD_BASE}, natural bun/patty/veg/sauce layers, not collapsed"
)

_HF_STUDIO_COFFEE_DRINK_SUBJECT = (
    f"{_HF_STUDIO_FOOD_BASE}, preserve cup shape and drink layers as in photo, "
    "no added foam/toppings not in original"
)

# --- studio scene tags per food type ---
# ref openai: _STUDIO_*_SCENE

_HF_STUDIO_SOUP_STEW_SCENE = (
    f"{_HF_STUDIO_SCENE_BASE}, warm wood-tone table, soft warm light"
)

_HF_STUDIO_FRIED_SCENE = (
    f"{_HF_STUDIO_SCENE_BASE}, warm neutral table, soft side light"
)

_HF_STUDIO_GRILLED_BBQ_SCENE = (
    f"{_HF_STUDIO_SCENE_BASE}, dark warm table tone, soft side light, natural contrast"
)

_HF_STUDIO_RICE_DISH_SCENE = (
    f"{_HF_STUDIO_SCENE_BASE}, bright clean table, soft even light, full bowl in frame"
)

_HF_STUDIO_BREAD_DESSERT_SCENE = (
    f"{_HF_STUDIO_SCENE_BASE}, bright cafe table, soft diffused light, full dessert in frame"
)

_HF_STUDIO_BURGER_SANDWICH_SCENE = (
    f"{_HF_STUDIO_SCENE_BASE}, casual dining table, soft side light, full sandwich in frame"
)

_HF_STUDIO_COFFEE_DRINK_SCENE = (
    f"{_HF_STUDIO_SCENE_BASE}, clean cafe table, soft natural window light, full cup in frame"
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

_HF_STUDIO_TEMPLATE = _HF_STUDIO_PHOTO_TEMPLATE


# =============================================================================
# 2. Poster
# =============================================================================

HF_POSTER_LAYOUT_RULES = (
    "LAYOUT 2:3 portrait 1024x1536: upper 38-44% quiet designed background zone (headline/menu added later), "
    "food hero anchored in LOWER half (vertical center of food below 62% height), "
    "never center food in frame, food base near bottom 10-15% margin on simple surface, "
    "keep both top-left and upper-center calm enough for adaptive editorial typography, "
    "keep the bottom 8% calm for a full-width store footer but continue the same background naturally, "
    "with no footer panel, color band, or hard horizontal split. "
    "{store_footer_line}"
)

_HF_POSTER_PHOTO_TEMPLATE = """
TASK: menu promo poster from attached food photo — food hero + designed background only, zero typography (HF img2img)
TYPE: {food_type_label}
{user_priority_block}{poster_layout_rules}
SUBJECT: {poster_food_rules}
BG: {poster_background_rules}
QUALITY: {realism_rules}
MOOD: appetizing commercial promo atmosphere, TONE: {tone}
CRITICAL: image pixels must have no readable text (Korean/English), no numbers, no labels
PRESERVE: preserve food shape/vessel, redesign bg/lighting only, typography is post-process overlay not in image
NEG: {hf_negative_poster}, no cafe interior, no restaurant room, no wood wall, no photo backdrop, no brand copy, no footer strip, no lower color block, no hard horizontal band
""".strip()

# --- poster food tags ---
# ref openai: _POSTER_*_FOOD

_HF_POSTER_SOUP_STEW_FOOD = (
    f"{_HF_POSTER_FOOD_BASE}, main pot only no side plates, glossy broth, "
    "moderate hero scale not oversized closeup, "
    "pot/bowl occupies 32-42% of frame height and max 50-58% of frame width, "
    "visible empty background margin around vessel on all sides, "
    "tall pot/bowl base near bottom edge, pot rim must stay below vertical midpoint"
)

_HF_POSTER_FRIED_FOOD = (
    f"{_HF_POSTER_FOOD_BASE}, crispy golden fried chicken/crust, not soggy"
)

_HF_POSTER_GRILLED_BBQ_FOOD = (
    f"{_HF_POSTER_FOOD_BASE}, grill marks, sear gloss, char texture"
)

_HF_POSTER_RICE_DISH_FOOD = (
    f"{_HF_POSTER_FOOD_BASE}, rice/noodle+topping layers visible"
)

_HF_POSTER_BREAD_DESSERT_FOOD = (
    f"{_HF_POSTER_FOOD_BASE}, crumb/cream/topping detail"
)

_HF_POSTER_BURGER_SANDWICH_FOOD = (
    f"{_HF_POSTER_FOOD_BASE}, bun/patty/cheese/sauce layers appetizing"
)

_HF_POSTER_COFFEE_DRINK_FOOD = (
    f"{_HF_POSTER_FOOD_BASE}, cup shape, foam/ice/beverage layers clear, "
    "no straw, no stirrer, no drinking accessories, open cup rim visible"
)

# --- poster background tags ---
# ref openai: _POSTER_*_BACKGROUND

_HF_POSTER_SOUP_STEW_BACKGROUND = (
    f"{_HF_POSTER_BG_BASE}, warm cream-to-terracotta solid gradient, appetizing hot-meal mood"
)

_HF_POSTER_FRIED_BACKGROUND = (
    f"{_HF_POSTER_BG_BASE}, warm orange-to-gold solid gradient, bright appetizing tone"
)

_HF_POSTER_GRILLED_BBQ_BACKGROUND = (
    f"{_HF_POSTER_BG_BASE}, deep charcoal-to-brown solid gradient, premium contrast"
)

_HF_POSTER_RICE_DISH_BACKGROUND = (
    f"{_HF_POSTER_BG_BASE}, light beige-to-warm ivory solid gradient, clean meal promo"
)

_HF_POSTER_BREAD_DESSERT_BACKGROUND = (
    f"{_HF_POSTER_BG_BASE}, pastel cream-to-latte solid gradient, soft dessert promo"
)

_HF_POSTER_BURGER_SANDWICH_BACKGROUND = (
    f"{_HF_POSTER_BG_BASE}, warm red-to-mustard solid gradient, bold casual promo"
)

_HF_POSTER_COFFEE_DRINK_BACKGROUND = (
    f"{_HF_POSTER_BG_BASE}, soft white-to-matcha green solid gradient, minimal drink promo"
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

_HF_POSTER_TEMPLATE = _HF_POSTER_PHOTO_TEMPLATE


# =============================================================================
# 3. Reels (instagram_feed)
# =============================================================================

HF_REELS_FOOD_RULES = (
    f"{_HF_SUBJECT_HERO_COMMON}, extreme closeup 70-85%, main dominant, sides at edges only"
)

HF_REELS_SCENE_RULES = (
    "preserve original restaurant/store interior, table decor, lighting, signage, "
    "shallow bokeh ok, no studio table/solid bg replacement, "
    "smartphone restaurant reels thumbnail, bright sharp appetizing, "
    "45deg or slight top-down, no people, bottom-left 20% empty for PIL"
)

HF_REELS_SCENE_RULES_FLEXIBLE = (
    "preserve restaurant/store interior from photo, user may adjust lighting/mood/color/table "
    "within same in-store location, no studio/solid bg replacement, extreme closeup 70-85%, "
    "no people, bottom-left 20% empty for PIL"
)

HF_REELS_REALISM_EXTRA = (
    "authentic in-store smartphone single shot, not studio reshoot/composite, "
    "food+bg same location same shoot, no fake bokeh/over-sharpen/CG ad look"
)

_HF_REELS_PHOTO_TEMPLATE = """
TASK: reels food thumbnail from in-store photo — faithful food, zero typography (HF img2img)
TYPE: {food_type_label}
{user_priority_block}SUBJECT: {reels_food_rules}
SCENE: {reels_scene_rules}
QUALITY: {realism_rules}, {reels_realism_extra}
MOOD: appetizing in-store atmosphere, TONE: {tone}
CRITICAL: image pixels must have no readable text (Korean/English), no numbers, no caption/hook text
PRESERVE: keep food appearance and store interior/bg faithful to photo; hook caption is PIL overlay only
NEG: {hf_negative_reels}
""".strip()

_HF_REELS_TEMPLATE = _HF_REELS_PHOTO_TEMPLATE


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

    user_priority_block = openai_prompts._build_user_priority_block(extra_notes)  # noqa: SLF001
    if user_priority_block:
        user_priority_block = user_priority_block + "\n"

    poster_food = openai_prompts._poster_food_rules_with_menu(  # noqa: SLF001
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
        "user_priority_block": user_priority_block,
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
        "hf_negative_studio": build_hf_variant_negative_prompt("studio"),
        "hf_negative_poster": build_hf_variant_negative_prompt("poster"),
        "hf_negative_reels": build_hf_variant_negative_prompt("instagram_feed"),
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
    if variant == "poster":
        return _require_hf(HF_NEGATIVE_POSTER, "HF_NEGATIVE_POSTER")
    if variant == "instagram_feed":
        return _require_hf(HF_NEGATIVE_REELS, "HF_NEGATIVE_REELS")
    if variant == "studio":
        return _require_hf(HF_NEGATIVE_STUDIO, "HF_NEGATIVE_STUDIO")
    return _require_hf(HF_NEGATIVE_COMMON, "HF_NEGATIVE_COMMON")


def strip_prompt_neg_line(prompt: str) -> str:
    """positive prompt에서 NEG: 줄을 제거한다 (HF negative 파라미터로 분리)."""

    lines = [line for line in prompt.splitlines() if not line.strip().startswith("NEG:")]
    return "\n".join(lines).strip()
