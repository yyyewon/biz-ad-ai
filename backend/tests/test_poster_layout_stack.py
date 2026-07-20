"""포스터 메뉴명·카피·가격 pill 스택 레이아웃 테스트."""

from app.utils.poster_layout import (
    PosterLayoutSpec,
    PosterPaletteSpec,
)


def _dummy_palette() -> PosterPaletteSpec:
    return PosterPaletteSpec(
        primary_text=(40, 50, 30),
        primary_stroke=(20, 25, 15),
        accent_text=(60, 90, 40),
        store_text=(50, 60, 45),
        store_stroke=(30, 35, 25),
        badge_fill=(248, 245, 238),
        badge_outline=(60, 90, 40),
        badge_text=(40, 50, 30),
    )


def _layout_with_food(*, food_top: int = 360) -> PosterLayoutSpec:
    width, height = 400, 600
    food_bbox = (60, food_top, 340, 560)
    return PosterLayoutSpec(
        width=width,
        height=height,
        food_bbox=food_bbox,
        content_top_y=int(height * 0.045),
        text_zone_bottom=food_top - 12,
        max_text_width=int(width * 0.88),
        line_gap=7,
        stroke_width=1,
        price_badge_cx=300,
        price_badge_cy_hint=96,
        store_margin_right=22,
        store_margin_bottom=25,
        palette=_dummy_palette(),
        scrim_height=180,
        scrim_max_alpha=80,
        used_fallback=False,
    )


def test_copy_anchors_to_top_not_food():
    layout = _layout_with_food(food_top=360)
    margin_top = max(layout.content_top_y, int(layout.height * 0.03))

    copy_y, menu_y = layout.resolve_text_stack_y(
        menu_block_height=70,
        copy_block_height=130,
    )

    assert copy_y == margin_top
    assert menu_y > copy_y + 130


def test_menu_anchors_to_food_visual_top():
    layout = _layout_with_food(food_top=360)
    menu_h = 70

    _, menu_y = layout.resolve_text_stack_y(
        menu_block_height=menu_h,
        copy_block_height=130,
    )

    pad = layout._menu_food_gap(menu_h)
    assert menu_y == max(layout.content_top_y, 360 - pad - menu_h)


def test_tall_copy_does_not_pull_copy_down_with_menu():
    layout = _layout_with_food(food_top=250)
    margin_top = max(layout.content_top_y, int(layout.height * 0.03))

    copy_y, menu_y = layout.resolve_text_stack_y(
        menu_block_height=90,
        copy_block_height=170,
    )

    assert copy_y == margin_top
    assert menu_y < copy_y + 170


def test_price_pill_sits_below_menu_block():
    layout = _layout_with_food()
    menu_bottom = 300
    badge_w, badge_h = 120, 44

    _, badge_cy = layout.resolve_price_badge_food_top_right(
        badge_width=badge_w,
        badge_height=badge_h,
        menu_block_bottom=menu_bottom,
        respect_menu_block=True,
    )

    badge_top = badge_cy - badge_h // 2
    assert badge_top >= menu_bottom + 8


def test_price_pill_overlaps_food_shoulder():
    layout = _layout_with_food(food_top=360)
    badge_w, badge_h = 120, 44

    cx, cy = layout.resolve_price_badge_food_top_right(
        badge_width=badge_w,
        badge_height=badge_h,
        respect_menu_block=False,
    )

    assert layout.badge_overlaps_food(
        center_x=cx,
        center_y=cy,
        badge_width=badge_w,
        badge_height=badge_h,
    )


def test_menu_anchors_to_visual_top_not_refined_body():
    layout = PosterLayoutSpec(
        width=400,
        height=600,
        food_bbox=(60, 320, 340, 560),
        food_visual_top=250,
        content_top_y=27,
        text_zone_bottom=230,
        max_text_width=350,
        line_gap=7,
        stroke_width=1,
        price_badge_cx=300,
        price_badge_cy_hint=96,
        store_margin_right=22,
        store_margin_bottom=25,
        palette=_dummy_palette(),
        scrim_height=180,
        scrim_max_alpha=80,
        used_fallback=False,
    )
    menu_h = 80
    menu_y_refined_only = PosterLayoutSpec(
        width=400,
        height=600,
        food_bbox=(60, 320, 340, 560),
        content_top_y=27,
        text_zone_bottom=230,
        max_text_width=350,
        line_gap=7,
        stroke_width=1,
        price_badge_cx=300,
        price_badge_cy_hint=96,
        store_margin_right=22,
        store_margin_bottom=25,
        palette=_dummy_palette(),
        scrim_height=180,
        scrim_max_alpha=80,
        used_fallback=False,
    ).resolve_text_stack_y(menu_block_height=menu_h, copy_block_height=0)[1]

    _, menu_y = layout.resolve_text_stack_y(menu_block_height=menu_h, copy_block_height=0)

    assert menu_y < menu_y_refined_only


def test_refine_food_bbox_shrinks_straw_at_top():
    from PIL import Image

    from app.utils.poster_layout import _refine_food_bbox

    width, height = 400, 600
    alpha = Image.new("L", (width, height), 0)
    # 컵 본체
    for x in range(120, 280):
        for y in range(280, 520):
            alpha.putpixel((x, y), 255)
    # 빨대 (얇은 상단 노이즈)
    for y in range(120, 280):
        alpha.putpixel((198, y), 255)

    raw_bbox = alpha.getbbox()
    assert raw_bbox is not None
    refined = _refine_food_bbox(alpha, raw_bbox, width, height)

    assert refined[1] > raw_bbox[1] + 40


def test_accent_should_use_rules_rejects_white_on_light_bg():
    from app.utils.poster_layout import _accent_should_use_rules

    light_bg = (220, 235, 210)
    assert _accent_should_use_rules((255, 255, 255), light_bg)
    assert not _accent_should_use_rules((58, 92, 38), light_bg)


def test_clamp_menu_block_y_lifts_when_overlapping_food():
    layout = _layout_with_food(food_top=180)
    menu_h = 90
    menu_y, used_fallback = layout.clamp_menu_block_y(
        150,
        menu_h,
        text_width=280,
    )

    assert menu_y + menu_h <= 180 - 8
    assert not used_fallback


def test_clamp_menu_block_y_uses_top_band_when_food_too_high():
    layout = _layout_with_food(food_top=120)
    menu_h = 120
    menu_y, used_fallback = layout.clamp_menu_block_y(
        80,
        menu_h,
        text_width=300,
    )

    assert used_fallback
    assert menu_y <= int(layout.height * 0.20)


def test_price_safe_zone_stays_above_food():
    layout = _layout_with_food(food_top=180)
    badge_w, badge_h = 120, 44
    menu_bottom = 150

    _, badge_cy = layout.resolve_price_badge_safe_zone(
        badge_width=badge_w,
        badge_height=badge_h,
        menu_block_bottom=menu_bottom,
    )

    badge_bottom = badge_cy + badge_h // 2
    assert badge_bottom <= 180 - 8


def test_clamp_menu_block_y_respects_copy_floor():
    layout = _layout_with_food(food_top=180)
    menu_h = 90
    copy_floor = 200

    menu_y, used_fallback = layout.clamp_menu_block_y(
        250,
        menu_h,
        text_width=280,
        min_y=copy_floor,
        allow_lift=True,
    )

    assert menu_y >= copy_floor
    assert used_fallback


def test_clamp_menu_block_y_copy_column_does_not_lift_above_floor():
    layout = _layout_with_food(food_top=220)
    menu_h = 100
    copy_floor = 210

    menu_y, used_fallback = layout.clamp_menu_block_y(
        copy_floor,
        menu_h,
        text_width=200,
        left_x=40,
        min_y=copy_floor,
        allow_lift=False,
    )

    assert menu_y == copy_floor
    assert used_fallback


def test_text_block_overlaps_food_left_aligned():
    layout = _layout_with_food(food_top=200)
    left_x = 40
    text_w = 200
    menu_y = 170
    menu_h = 50

    assert layout.text_block_overlaps_food(
        top_y=menu_y,
        block_height=menu_h,
        text_width=text_w,
        left_x=left_x,
    )
    assert not layout.text_block_overlaps_food(
        top_y=120,
        block_height=menu_h,
        text_width=text_w,
        left_x=left_x,
    )


def test_clamp_text_block_top_left_lifts_above_food():
    layout = PosterLayoutSpec(
        width=400,
        height=600,
        food_bbox=(60, 120, 340, 560),
        content_top_y=27,
        text_zone_bottom=108,
        max_text_width=350,
        line_gap=7,
        stroke_width=1,
        price_badge_cx=300,
        price_badge_cy_hint=96,
        store_margin_right=22,
        store_margin_bottom=25,
        palette=_dummy_palette(),
        scrim_height=180,
        scrim_max_alpha=80,
        used_fallback=False,
    )
    _, y = layout.clamp_text_block_top_left(
        x=40,
        y=100,
        block_width=200,
        block_height=80,
    )
    assert y + 80 <= 120


def test_badge_overlaps_food_detects_pill_on_food():
    layout = _layout_with_food(food_top=200)
    assert layout.badge_overlaps_food(
        center_x=300,
        center_y=250,
        badge_width=120,
        badge_height=44,
    )
    assert not layout.badge_overlaps_food(
        center_x=300,
        center_y=120,
        badge_width=120,
        badge_height=44,
    )
