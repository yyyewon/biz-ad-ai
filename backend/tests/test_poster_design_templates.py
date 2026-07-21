from __future__ import annotations

import io
import hashlib

import pytest
from PIL import Image, ImageDraw

from app.utils.image_bytes import pil_image_to_png_bytes
from app.utils.image_text_overlay import (
    PosterOverlayCopy,
    _format_price_text,
    composite_poster_text,
)
from app.utils.poster_layout import PosterLayoutSpec, PosterPaletteSpec
from app.utils.poster_template import apply_template_overrides, resolve_poster_template


@pytest.mark.parametrize(
    ("tone", "composition", "price_style"),
    [
        ("캐주얼·친근", "centered", "ticket"),
        ("정중·신뢰", "framed", "ticket"),
        ("고급·감성", "editorial", "label"),
        ("유머·이벤트", "centered", "stamp"),
    ],
)
def test_tone_selects_distinct_poster_art_direction(
    tone: str,
    composition: str,
    price_style: str,
) -> None:
    template = resolve_poster_template(tone)

    assert template.composition == composition
    assert template.price_style == price_style


def test_explicit_composition_override_preserves_other_template_tokens() -> None:
    base = resolve_poster_template("고급·감성")

    overridden = apply_template_overrides(
        base,
        {"composition": "framed", "price_style": "ticket"},
    )

    assert overridden.composition == "framed"
    assert overridden.price_style == "ticket"
    assert overridden.menu_size_ratio == base.menu_size_ratio


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("7000원", "7,000원"),
        ("10,000 원", "10,000원"),
        ("가격 문의", "가격 문의"),
    ],
)
def test_price_text_uses_readable_thousands_separator(source: str, expected: str) -> None:
    assert _format_price_text(source) == expected


def _preview_layout(image: Image.Image) -> PosterLayoutSpec:
    width, height = image.size
    alpha = Image.new("L", image.size, 0)
    ImageDraw.Draw(alpha).ellipse((22, 235, width - 22, 475), fill=255)
    palette = PosterPaletteSpec(
        primary_text=(76, 49, 29),
        primary_stroke=(246, 232, 207),
        accent_text=(49, 30, 18),
        store_text=(76, 49, 29),
        store_stroke=(246, 232, 207),
        badge_fill=(250, 245, 236),
        badge_outline=(76, 49, 29),
        badge_text=(49, 30, 18),
    )
    return PosterLayoutSpec(
        width=width,
        height=height,
        food_bbox=(22, 235, width - 22, 475),
        food_visual_top=235,
        content_top_y=20,
        text_zone_bottom=225,
        max_text_width=int(width * 0.86),
        line_gap=7,
        stroke_width=2,
        price_badge_cx=int(width * 0.78),
        price_badge_cy_hint=62,
        store_margin_right=22,
        store_margin_bottom=20,
        palette=palette,
        scrim_height=0,
        scrim_max_alpha=0,
        used_fallback=False,
        foreground_alpha=alpha,
    )


def test_manual_design_styles_render_distinct_images() -> None:
    image = Image.new("RGB", (400, 600), (232, 203, 165))
    food_draw = ImageDraw.Draw(image)
    food_draw.ellipse((22, 235, 378, 475), fill=(247, 238, 218))
    food_draw.polygon(((72, 380), (218, 250), (334, 340), (320, 420), (84, 438)), fill=(96, 48, 24))
    source_bytes = pil_image_to_png_bytes(image)
    copy = PosterOverlayCopy(
        headline="오늘의 한 접시",
        subline="천천히 즐겨보세요",
        sticker="SPECIAL",
        menu_name="시그니처 메뉴",
        price_text="12,000원",
        store_name="새벽",
    )
    layout = _preview_layout(image)

    rendered: list[bytes] = []
    for style in ("editorial", "centered", "framed"):
        result = composite_poster_text(
            source_bytes,
            copy,
            tone="고급·감성",
            food_type="bread_dessert",
            design_style=style,
            layout=layout,
        )
        output = Image.open(io.BytesIO(result))
        assert output.size == image.size
        rendered.append(result)

    assert len({hashlib.sha256(bytes_).hexdigest() for bytes_ in rendered}) == 3
