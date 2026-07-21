"""Render the four built-in poster tones on one background for visual QA."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from app.utils.image_bytes import pil_image_to_png_bytes
from app.utils.image_text_overlay import PosterOverlayCopy, composite_poster_text
from app.utils.poster_layout import PosterLayoutSpec, PosterPaletteSpec
from app.utils.poster_taglines import resolve_poster_copy


TONES: tuple[tuple[str, str], ...] = (
    ("캐주얼·친근", "casual"),
    ("정중·신뢰", "trust"),
    ("고급·감성", "premium"),
    ("유머·이벤트", "event"),
)


def _build_preview_layout(image: Image.Image) -> PosterLayoutSpec:
    width, height = image.size
    foreground_alpha = Image.new("L", image.size, 0)
    mask = ImageDraw.Draw(foreground_alpha)
    mask.ellipse(
        (
            int(width * 0.025),
            int(height * 0.405),
            int(width * 0.985),
            int(height * 0.795),
        ),
        fill=255,
    )
    mask.polygon(
        (
            (int(width * 0.16), int(height * 0.535)),
            (int(width * 0.60), int(height * 0.35)),
            (int(width * 0.86), int(height * 0.45)),
            (int(width * 0.88), int(height * 0.63)),
            (int(width * 0.18), int(height * 0.69)),
        ),
        fill=255,
    )
    palette = PosterPaletteSpec(
        primary_text=(85, 54, 31),
        primary_stroke=(246, 229, 201),
        accent_text=(55, 31, 17),
        store_text=(91, 63, 39),
        store_stroke=(246, 229, 201),
        badge_fill=(249, 243, 232),
        badge_outline=(91, 55, 31),
        badge_text=(55, 31, 17),
    )
    food_top = int(height * 0.35)
    return PosterLayoutSpec(
        width=width,
        height=height,
        food_bbox=(
            int(width * 0.025),
            food_top,
            int(width * 0.985),
            int(height * 0.80),
        ),
        food_visual_top=food_top,
        content_top_y=int(height * 0.052),
        text_zone_bottom=int(height * 0.335),
        max_text_width=int(width * 0.87),
        line_gap=max(7, int(height * 0.009)),
        stroke_width=max(1, int(width * 0.002)),
        price_badge_cx=int(width * 0.76),
        price_badge_cy_hint=int(height * 0.13),
        store_margin_right=int(width * 0.065),
        store_margin_bottom=int(height * 0.042),
        palette=palette,
        scrim_height=0,
        scrim_max_alpha=0,
        used_fallback=False,
        foreground_alpha=foreground_alpha,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    base = Image.open(args.base).convert("RGB")
    source = pil_image_to_png_bytes(base)
    layout = _build_preview_layout(base)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for tone, slug in TONES:
        tagline = resolve_poster_copy("매장 분위기 소개", tone)
        overlay = PosterOverlayCopy(
            headline=tagline.headline,
            subline=tagline.subline,
            sticker=tagline.sticker,
            menu_name="치즈케이크",
            price_text="7000원",
            store_name="새벽",
        )
        rendered = composite_poster_text(
            source,
            overlay,
            tone=tone,
            food_type="bread_dessert",
            layout=layout,
        )
        (args.output_dir / f"poster_tone_{slug}.png").write_bytes(rendered)


if __name__ == "__main__":
    main()
