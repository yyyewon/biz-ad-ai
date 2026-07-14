from app.schemas.image_ad import ImageAdRequest
from app.services.pipelines.food_type_prompts import (
    build_food_variant_prompt,
    build_poster_exact_text_block,
    uses_custom_template,
)
from app.services.pipelines.image_pipeline import _build_poster_prompt
from app.utils.image_text_overlay import variant_uses_pil_text_overlay


def _payload(**kwargs) -> ImageAdRequest:
    defaults = {
        "store_name": "온기식당",
        "menu_name": "고추장 찌개",
        "food_type": "fried",
        "promotion_goal": "신메뉴 홍보",
        "tone": "친근한",
        "extra_notes": "따뜻한 나무 테이블 배경",
        "num_images": 3,
    }
    defaults.update(kwargs)
    return ImageAdRequest(**defaults)


def test_user_image_request_is_priority_block_in_studio_prompt():
    prompt = build_food_variant_prompt(
        _payload(),
        "studio",
        food_type="fried",
        build_poster_prompt=_build_poster_prompt,
    )

    assert "PRIORITY:" in prompt
    assert "따뜻한 나무 테이블 배경" in prompt
    assert prompt.index("PRIORITY:") < prompt.index("SUBJECT:")


def test_studio_prompt_polishes_without_food_exaggeration():
    prompt = build_food_variant_prompt(
        _payload(food_type="coffee_drink"),
        "studio",
        food_type="coffee_drink",
        build_poster_prompt=_build_poster_prompt,
    )

    assert "polish attached casual" in prompt
    assert "editorial food reshoot" not in prompt
    assert "PRESERVE:" in prompt
    assert "faithful to photo" in prompt
    assert "no added foam" in prompt
    assert "no exaggerated gloss" in prompt
    assert "foam/cream texture" not in prompt


def test_fried_poster_uses_custom_template_with_pil_rules():
    assert uses_custom_template("fried", "poster") is True
    assert variant_uses_pil_text_overlay("fried", "poster") is True

    prompt = build_food_variant_prompt(
        _payload(food_type="fried", price_text="7,000원", store_location="성수동"),
        "poster",
        food_type="fried",
        build_poster_prompt=_build_poster_prompt,
    )

    assert "crispy golden fried" in prompt
    assert "casual dining poster" in prompt
    assert "PIL" in prompt
    assert "PIL post-process" in prompt
    assert "location context" not in prompt
    assert "성수동" not in prompt
    assert "EXACT TEXT" not in prompt


def test_poster_exact_text_block_still_available_for_helpers():
    block = build_poster_exact_text_block(
        headline="신메뉴 출시",
        menu_name="고추장 찌개",
        price_text="8000원",
        store_name="온기식당",
    )
    assert '"8000원" — price' in block


def test_reels_uses_flexible_scene_rules_when_background_requested():
    prompt = build_food_variant_prompt(
        _payload(extra_notes="배경을 더 밝게"),
        "instagram_feed",
        food_type="fried",
        build_poster_prompt=_build_poster_prompt,
    )

    assert "user may override" in prompt
    assert "keep original store interior" not in prompt


def test_reels_prompt_excludes_menu_name_from_image_model():
    prompt = build_food_variant_prompt(
        _payload(menu_name="고추장 찌개"),
        "instagram_feed",
        food_type="fried",
        build_poster_prompt=_build_poster_prompt,
    )

    assert "고추장 찌개" not in prompt
    assert "menu title" in prompt
    assert "hook via PIL" in prompt


def test_reels_variant_uses_pil_overlay():
    assert variant_uses_pil_text_overlay("fried", "instagram_feed") is True


def test_common_clutter_exclusion_in_all_food_types_and_variants():
    clutter_markers = (
        "empty plates",
        "water cups",
        "hero focus on ordered menu item",
    )
    negative_markers = ("no empty plate", "no water cup", "no napkin")

    for food_type in (
        "soup_stew",
        "fried",
        "grilled_bbq",
        "rice_dish",
        "bread_dessert",
        "burger_sandwich",
        "coffee_drink",
    ):
        for variant in ("studio", "poster", "instagram_feed"):
            prompt = build_food_variant_prompt(
                _payload(food_type=food_type),
                variant,
                food_type=food_type,
                build_poster_prompt=_build_poster_prompt,
            )
            for marker in clutter_markers:
                assert marker in prompt, f"{food_type}/{variant} missing {marker}"
            for marker in negative_markers:
                assert marker in prompt, f"{food_type}/{variant} missing {marker}"
