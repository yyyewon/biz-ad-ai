from app.schemas.image_ad import ImageAdRequest
from app.services.pipelines.food_type_prompts import (
    build_food_variant_prompt,
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

    assert "[최우선 — 사용자 이미지 요청]" in prompt
    assert "따뜻한 나무 테이블 배경" in prompt
    assert prompt.index("[최우선 — 사용자 이미지 요청]") < prompt.index("[음식 유지 — 튀김")


def test_fried_poster_uses_custom_template_with_food_rules():
    assert uses_custom_template("fried", "poster") is True
    assert variant_uses_pil_text_overlay("fried", "poster") is False

    prompt = build_food_variant_prompt(
        _payload(food_type="fried"),
        "poster",
        food_type="fried",
        build_poster_prompt=_build_poster_prompt,
    )

    assert "포스터 히어로 컷 · 튀김" in prompt
    assert "배경·디자인 — 튀김 포스터" in prompt
    assert "메뉴명 (가장 크고 굵게)" in prompt
    assert "PIL" not in prompt


def test_reels_uses_flexible_scene_rules_when_background_requested():
    prompt = build_food_variant_prompt(
        _payload(extra_notes="배경을 더 밝게"),
        "instagram_feed",
        food_type="fried",
        build_poster_prompt=_build_poster_prompt,
    )

    assert "사용자 배경·연출 요청 반영" in prompt
    assert "매장 배경 유지" not in prompt


def test_reels_variant_uses_pil_overlay():
    assert variant_uses_pil_text_overlay("fried", "instagram_feed") is True
