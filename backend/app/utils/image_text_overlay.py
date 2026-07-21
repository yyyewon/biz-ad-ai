"""
인스타 릴스·포스터 이미지에 한국어 텍스트를 PIL로 합성한다.

포스터: AI는 배경+음식만 생성, 카피·메뉴명·가격 pill·가게명은 PIL 합성.
       rembg 기반 LayoutSpec으로 배치·배경색·scrim을 적용한다.
릴스: 하단 후킹 자막 PIL 합성.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from app.schemas.image_ad import ImageAdRequest, ImageVariantType
from app.services.pipelines.food_type_prompts import uses_custom_template
from app.utils.font_registry import TextOverlayRole, load_overlay_font
from app.utils.image_bytes import image_bytes_to_pil, pil_image_to_png_bytes
from app.utils.poster_layout import (
    PosterLayoutSpec,
    PosterPaletteSpec,
    _COPY_COLUMN_MAX_WIDTH_RATIO,
    analyze_poster_layout,
)
from app.utils.poster_template import (
    PosterTemplateSpec,
    _RATIO_BOUNDS,
    resolve_poster_template_for_layout,
)
from app.utils.poster_taglines import resolve_poster_copy
from app.utils.reels_hooks import ReelsHookCopy, resolve_reels_hook_lines


@dataclass(frozen=True)
class PosterOverlayCopy:
    headline: str
    subline: str
    sticker: str
    menu_name: str
    price_text: str
    store_name: str


_MENU_FONT_SHRINK_FACTOR = 0.92
_MAX_FONT_SHRINK_STEPS = 8
_INTRUSION_MENU_RATIO_SCALE = 0.88


@dataclass(frozen=True)
class _PosterMenuPlacementPlan:
    menu_start_y: int
    menu_block_height: int
    menu_lines: list[str]
    menu_font: ImageFont.FreeTypeFont
    price_font: ImageFont.FreeTypeFont
    menu_align: str
    menu_x: int
    menu_max_width: int
    layout_mode: str
    font_scale: float
    overlaps_food: bool


def variant_uses_pil_text_overlay(food_type: str | None, variant: ImageVariantType) -> bool:
    if not food_type:
        return False
    if variant not in ("instagram_feed", "poster"):
        return False
    return uses_custom_template(food_type, variant)  # type: ignore[arg-type]


def build_reels_overlay_copy(payload: ImageAdRequest) -> ReelsHookCopy:
    return resolve_reels_hook_lines(
        payload.promotion_goal or "",
        store_name=payload.store_name or "",
        menu_name=payload.menu_name or "",
        store_location=payload.store_location or "",
        price_text=payload.price_text or "",
    )


def build_poster_overlay_copy(payload: ImageAdRequest) -> PosterOverlayCopy:
    tagline = resolve_poster_copy(
        payload.promotion_goal or "",
        payload.tone,
    )
    headline = (payload.headline or "").strip() or tagline.headline

    return PosterOverlayCopy(
        headline=headline,
        subline=tagline.subline,
        sticker=tagline.sticker,
        menu_name=(payload.menu_name or "").strip() or "오늘의 메뉴",
        price_text=(payload.price_text or "").strip(),
        store_name=(payload.store_name or "").strip(),
    )


def _scale_overlay_font(
    image: Image.Image,
    role: TextOverlayRole,
    ratio: float,
    *,
    tone: str | None = None,
    food_type: str | None = None,
    variant: str | None = None,
) -> ImageFont.FreeTypeFont:
    size = max(12, int(image.width * ratio))
    return load_overlay_font(
        role,
        size,
        tone=tone,
        food_type=food_type,
        variant=variant,
    )


def _wrap_text(
    text: str,
    *,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    if " " in text:
        words = text.split()
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    lines: list[str] = []
    current = ""
    for char in text:
        candidate = f"{current}{char}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def _draw_stroked_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    stroke_fill: tuple[int, int, int],
    stroke_width: int,
) -> None:
    draw.text(
        xy,
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )


def _centered_x(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> int:
    return int((width - draw.textlength(text, font=font)) / 2)


def _poster_text_margin_x(image_width: int) -> int:
    return max(24, int(image_width * 0.08))


def _draw_left_line(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    fill: tuple[int, int, int],
) -> int:
    draw.text((x, y), text, font=font, fill=fill)
    ascent, descent = font.getmetrics()
    return ascent + descent


def _apply_poster_top_scrim(
    image: Image.Image,
    *,
    scrim_height: int,
    max_alpha: int,
) -> Image.Image:
    """상단 텍스트 가독성용 어두운 그라데이션."""

    if max_alpha <= 0 or scrim_height <= 0:
        return image

    width, height = image.size
    zone_h = min(scrim_height, height)
    scrim = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(scrim)

    for offset, y in enumerate(range(zone_h)):
        fade = 1.0 - (offset / max(zone_h, 1))
        alpha = int(max_alpha * fade * fade)
        draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    return Image.alpha_composite(image, scrim)


def _draw_centered_line(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    font: ImageFont.FreeTypeFont,
    y: int,
    image_width: int,
    fill: tuple[int, int, int],
    stroke_fill: tuple[int, int, int] | None = None,
    stroke_width: int = 0,
) -> int:
    x = _centered_x(draw, text, font, image_width)
    if stroke_width > 0 and stroke_fill is not None:
        _draw_stroked_text(
            draw,
            (x, y),
            text,
            font=font,
            fill=fill,
            stroke_fill=stroke_fill,
            stroke_width=stroke_width,
        )
    else:
        draw.text((x, y), text, font=font, fill=fill)
    ascent, descent = font.getmetrics()
    return ascent + descent


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_text_on_fill(
    fill_rgb: tuple[int, int, int],
    preferred_text: tuple[int, int, int],
) -> tuple[int, int, int]:
    fill_lum = _relative_luminance(fill_rgb)
    pref_lum = _relative_luminance(preferred_text)
    if fill_lum < 150:
        return (255, 255, 255)
    if pref_lum < fill_lum - 50:
        return preferred_text
    return (40, 45, 50)


def _draw_price_pill_badge(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    font: ImageFont.FreeTypeFont,
    center_x: int,
    center_y: int,
    image_width: int,
    palette: PosterPaletteSpec,
    template: PosterTemplateSpec,
) -> None:
    text_width = int(draw.textlength(text, font=font))
    ascent, descent = font.getmetrics()
    text_height = ascent + descent

    pad_x = max(10, int(image_width * template.badge_pad_x_ratio))
    pad_y = max(6, int(image_width * template.badge_pad_y_ratio))
    badge_w = text_width + pad_x * 2
    badge_h = text_height + pad_y * 2
    radius = badge_h // 2

    left = int(center_x - badge_w / 2)
    top = int(center_y - badge_h / 2)
    bbox = (left, top, left + badge_w, top + badge_h)
    outline_width = max(2, int(image_width * template.badge_outline_width_ratio))

    text_x = left + pad_x
    text_y = top + (badge_h - text_height) // 2

    if template.badge_style == "filled":
        fill = palette.badge_fill
        text_fill = _contrast_text_on_fill(fill, palette.badge_text)
        draw.rounded_rectangle(bbox, radius=radius, fill=fill)
        draw.text((text_x, text_y), text, font=font, fill=text_fill)
        return

    draw.rounded_rectangle(
        bbox,
        radius=radius,
        outline=palette.badge_outline,
        width=outline_width,
    )
    draw.text((text_x, text_y), text, font=font, fill=palette.badge_text)


def _sticker_pill_metrics(
    *,
    text: str,
    font: ImageFont.FreeTypeFont,
    image_width: int,
    draw: ImageDraw.ImageDraw,
) -> tuple[int, int]:
    text_width = int(draw.textlength(text, font=font))
    ascent, descent = font.getmetrics()
    text_height = ascent + descent
    pad_x = max(8, int(image_width * 0.022))
    pad_y = max(4, int(image_width * 0.010))
    return text_width + pad_x * 2, text_height + pad_y * 2


def _draw_poster_sticker_badge(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    font: ImageFont.FreeTypeFont,
    left_x: int,
    top_y: int,
    image_width: int,
    palette: PosterPaletteSpec,
) -> int:
    badge_w, badge_h = _sticker_pill_metrics(text=text, font=font, image_width=image_width, draw=draw)
    left = left_x
    bbox = (left, top_y, left + badge_w, top_y + badge_h)
    radius = badge_h // 2
    fill = palette.badge_fill
    text_fill = _contrast_text_on_fill(fill, palette.badge_text)
    draw.rounded_rectangle(bbox, radius=radius, fill=fill)
    ascent, descent = font.getmetrics()
    text_height = ascent + descent
    text_x = left + (badge_w - int(draw.textlength(text, font=font))) // 2
    text_y = top_y + (badge_h - text_height) // 2
    draw.text((text_x, text_y), text, font=font, fill=text_fill)
    return badge_h


def _measure_line_height(font: ImageFont.FreeTypeFont) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent


def _measure_copy_block_height(
    *,
    sticker: str,
    headline: str,
    subline: str,
    sticker_font: ImageFont.FreeTypeFont,
    headline_font: ImageFont.FreeTypeFont,
    subline_font: ImageFont.FreeTypeFont,
    copy_max_width: int,
    line_gap: int,
    image_width: int,
    draw: ImageDraw.ImageDraw,
) -> int:
    total = 0
    sticker = (sticker or "").strip()
    if sticker:
        _, badge_h = _sticker_pill_metrics(
            text=sticker,
            font=sticker_font,
            image_width=image_width,
            draw=draw,
        )
        total += badge_h + line_gap

    headline = (headline or "").strip()
    if headline:
        for _ in _wrap_text(
            headline,
            font=headline_font,
            max_width=copy_max_width,
            draw=draw,
        ):
            total += _measure_line_height(headline_font) + line_gap

    subline = (subline or "").strip()
    if subline:
        if headline:
            total += max(0, line_gap // 2)
        for _ in _wrap_text(
            subline,
            font=subline_font,
            max_width=copy_max_width,
            draw=draw,
        ):
            total += _measure_line_height(subline_font) + line_gap

    if total > 0:
        total -= line_gap
    return total


def _measure_menu_block_height(
    *,
    menu_name: str,
    menu_font: ImageFont.FreeTypeFont,
    menu_max_width: int,
    line_gap: int,
    draw: ImageDraw.ImageDraw,
) -> int:
    total = 0
    for _ in _wrap_text(
        menu_name,
        font=menu_font,
        max_width=menu_max_width,
        draw=draw,
    ):
        total += _measure_line_height(menu_font) + line_gap
    if total > 0:
        total -= line_gap
    return total


def _resolve_price_badge_placement(
    *,
    width: int,
    menu_lines: list[str],
    menu_font: ImageFont.FreeTypeFont,
    menu_start_y: int,
    menu_end_y: int,
    price_text: str,
    price_font: ImageFont.FreeTypeFont,
    layout: PosterLayoutSpec,
    template: PosterTemplateSpec,
    draw: ImageDraw.ImageDraw,
    menu_layout_mode: str = "center",
    menu_align: str = "center",
    menu_x: int = 0,
) -> tuple[int, int, int, int]:
    pad_x = max(10, int(width * template.badge_pad_x_ratio))
    pad_y = max(6, int(width * template.badge_pad_y_ratio))
    text_width = int(draw.textlength(price_text, font=price_font))
    ascent, descent = price_font.getmetrics()
    text_height = ascent + descent
    badge_w = text_width + pad_x * 2
    badge_h = text_height + pad_y * 2

    if menu_lines:
        badge_cy = int((menu_start_y + menu_end_y) / 2)
    else:
        badge_cy = layout.price_badge_cy_hint

    if template.price_anchor == "top_right":
        badge_cx, badge_cy = layout.resolve_price_badge_top_right(
            badge_width=badge_w,
            badge_height=badge_h,
        )
    elif template.price_anchor == "food_top_right" and layout.food_bbox:
        badge_cx, badge_cy = layout.resolve_price_badge_food_top_right(
            badge_width=badge_w,
            badge_height=badge_h,
            menu_block_bottom=menu_end_y if menu_lines else None,
            respect_menu_block=menu_layout_mode != "copy_column",
        )
    elif template.price_anchor == "food_top_right":
        badge_cx, badge_cy = layout.resolve_price_badge_safe_zone(
            badge_width=badge_w,
            badge_height=badge_h,
            menu_block_bottom=menu_end_y if menu_lines else None,
        )
    elif template.price_anchor == "menu_right" and menu_lines:
        max_menu_w = max(int(draw.textlength(line, font=menu_font)) for line in menu_lines)
        gap = max(10, int(width * 0.02))
        if menu_align == "left":
            menu_right_edge = menu_x + max_menu_w
        else:
            menu_right_edge = (width + max_menu_w) // 2
        badge_cx = int(menu_right_edge + gap + badge_w / 2)
        margin = max(12, int(width * 0.04))
        badge_cx = min(width - badge_w // 2 - margin, badge_cx)
        badge_cx = max(badge_w // 2 + margin, badge_cx)
        badge_cx, badge_cy = layout.clamp_price_badge_center(
            center_x=badge_cx,
            center_y=badge_cy,
            badge_width=badge_w,
            badge_height=badge_h,
        )
    else:
        badge_cx = layout.price_badge_cx
        badge_cx, badge_cy = layout.clamp_price_badge_center(
            center_x=badge_cx,
            center_y=badge_cy,
            badge_width=badge_w,
            badge_height=badge_h,
        )
    return badge_cx, badge_cy, badge_w, badge_h


def _resolve_poster_menu_placement(
    *,
    layout: PosterLayoutSpec,
    template: PosterTemplateSpec,
    image: Image.Image,
    menu_name: str,
    draw: ImageDraw.ImageDraw,
    tone: str | None,
    food_type: str | None,
    text_margin_x: int,
    copy_max_width: int,
    line_gap: int,
    copy_y: int,
    copy_block_height: int,
) -> _PosterMenuPlacementPlan:
    """메뉴명: 카피 블록 바로 아래 좌측 열."""

    menu_min_ratio = _RATIO_BOUNDS["menu_size_ratio"][0]
    price_min_ratio = _RATIO_BOUNDS["price_size_ratio"][0]
    menu_ratio = template.menu_size_ratio
    price_ratio = template.price_size_ratio

    if layout.food_intrudes_text_zone():
        menu_ratio = max(
            menu_min_ratio,
            menu_ratio * _INTRUSION_MENU_RATIO_SCALE,
        )
        price_ratio = max(
            price_min_ratio,
            price_ratio * _INTRUSION_MENU_RATIO_SCALE,
        )

    copy_gap = max(8, int(image.height * 0.012))
    copy_floor_y = copy_y + copy_block_height + copy_gap

    menu_lines: list[str] = []
    menu_block_height = 0
    menu_start_y = copy_floor_y
    max_menu_line_w = 0
    overlaps = False

    for step in range(_MAX_FONT_SHRINK_STEPS):
        menu_font = _scale_overlay_font(
            image,
            TextOverlayRole.POSTER_MENU,
            menu_ratio,
            tone=tone,
            food_type=food_type,
            variant="poster",
        )
        price_font = _scale_overlay_font(
            image,
            TextOverlayRole.POSTER_PRICE,
            price_ratio,
            tone=tone,
            food_type=food_type,
            variant="poster",
        )

        menu_lines = _wrap_text(
            menu_name,
            font=menu_font,
            max_width=copy_max_width,
            draw=draw,
        )
        menu_block_height = _measure_menu_block_height(
            menu_name=menu_name,
            menu_font=menu_font,
            menu_max_width=copy_max_width,
            line_gap=line_gap,
            draw=draw,
        )
        max_menu_line_w = (
            max(int(draw.textlength(line, font=menu_font)) for line in menu_lines)
            if menu_lines
            else copy_max_width
        )

        menu_y = copy_floor_y
        menu_y, _ = layout.clamp_menu_block_y(
            menu_y,
            menu_block_height,
            text_width=max_menu_line_w,
            left_x=text_margin_x,
            min_y=copy_floor_y,
            allow_lift=False,
        )

        overlaps = layout.text_block_overlaps_food(
            top_y=menu_y,
            block_height=menu_block_height,
            text_width=max_menu_line_w,
            left_x=text_margin_x,
        )

        if not overlaps:
            menu_start_y = menu_y
            break

        at_min = menu_ratio <= menu_min_ratio + 1e-6 and price_ratio <= price_min_ratio + 1e-6
        menu_start_y = menu_y
        if at_min or step >= _MAX_FONT_SHRINK_STEPS - 1:
            break

        menu_ratio = max(menu_min_ratio, menu_ratio * _MENU_FONT_SHRINK_FACTOR)
        price_ratio = max(price_min_ratio, price_ratio * _MENU_FONT_SHRINK_FACTOR)

    font_scale = menu_ratio / template.menu_size_ratio if template.menu_size_ratio else 1.0
    return _PosterMenuPlacementPlan(
        menu_start_y=menu_start_y,
        menu_block_height=menu_block_height,
        menu_lines=menu_lines,
        menu_font=menu_font,
        price_font=price_font,
        menu_align="left",
        menu_x=text_margin_x,
        menu_max_width=copy_max_width,
        layout_mode="copy_column",
        font_scale=font_scale,
        overlaps_food=overlaps,
    )


def composite_poster_text(
    image_bytes: bytes,
    overlay_copy: PosterOverlayCopy,
    *,
    tone: str | None = None,
    food_type: str | None = None,
    layout: PosterLayoutSpec | None = None,
) -> bytes:
    """
    포스터 PIL 합성:
    - rembg 기반 LayoutSpec으로 headline/menu/pill/store 배치
    - 배경 mask 색·scrim은 layout 분석 결과 사용
    - 정렬: 카피·메뉴 좌측 열, 가격 pill 우상단, 가게명 우하단 (위치는 규칙 고정)
    """
    image = image_bytes_to_pil(image_bytes).convert("RGBA")
    if layout is None:
        layout = analyze_poster_layout(image.convert("RGB"))

    image = _apply_poster_top_scrim(
        image,
        scrim_height=layout.scrim_height,
        max_alpha=layout.scrim_max_alpha,
    )
    palette = layout.palette
    template = resolve_poster_template_for_layout(
        tone,
        vlm_template=layout.vlm_template,
    )
    draw = ImageDraw.Draw(image)

    width, height = image.size
    text_margin_x = _poster_text_margin_x(width)
    copy_max_width = min(
        layout.max_text_width,
        int(width * _COPY_COLUMN_MAX_WIDTH_RATIO) - text_margin_x,
        width - text_margin_x * 2,
    )
    menu_max_width = layout.max_text_width
    line_gap = layout.line_gap

    headline_font = _scale_overlay_font(
        image,
        TextOverlayRole.POSTER_HEADLINE,
        template.headline_size_ratio,
        tone=tone,
        food_type=food_type,
        variant="poster",
    )
    subline_font = _scale_overlay_font(
        image,
        TextOverlayRole.POSTER_HEADLINE,
        template.subline_size_ratio,
        tone=tone,
        food_type=food_type,
        variant="poster",
    )
    sticker_font = _scale_overlay_font(
        image,
        TextOverlayRole.POSTER_PRICE,
        template.sticker_size_ratio,
        tone=tone,
        food_type=food_type,
        variant="poster",
    )
    store_font = _scale_overlay_font(
        image,
        TextOverlayRole.POSTER_STORE,
        template.store_size_ratio,
        tone=tone,
        food_type=food_type,
        variant="poster",
    )

    copy_block_height = _measure_copy_block_height(
        sticker=overlay_copy.sticker,
        headline=overlay_copy.headline,
        subline=overlay_copy.subline,
        sticker_font=sticker_font,
        headline_font=headline_font,
        subline_font=subline_font,
        copy_max_width=copy_max_width,
        line_gap=line_gap,
        image_width=width,
        draw=draw,
    )
    copy_y = max(
        layout.content_top_y,
        int(height * 0.03),
    )
    menu_plan = _resolve_poster_menu_placement(
        layout=layout,
        template=template,
        image=image,
        menu_name=overlay_copy.menu_name,
        draw=draw,
        tone=tone,
        food_type=food_type,
        text_margin_x=text_margin_x,
        copy_max_width=copy_max_width,
        line_gap=line_gap,
        copy_y=copy_y,
        copy_block_height=copy_block_height,
    )
    menu_font = menu_plan.menu_font
    price_font = menu_plan.price_font
    menu_lines = menu_plan.menu_lines
    menu_start_y = menu_plan.menu_start_y

    logger.info(
        "poster_menu_layout | mode=copy_column | font_scale={:.2f} | overlaps_food={}",
        menu_plan.font_scale,
        menu_plan.overlaps_food,
    )

    cursor_y = copy_y
    sticker_text = (overlay_copy.sticker or "").strip()
    if sticker_text:
        sticker_h = _draw_poster_sticker_badge(
            draw,
            text=sticker_text,
            font=sticker_font,
            left_x=text_margin_x,
            top_y=cursor_y,
            image_width=width,
            palette=palette,
        )
        cursor_y += sticker_h + line_gap

    if overlay_copy.headline:
        for line in _wrap_text(
            overlay_copy.headline,
            font=headline_font,
            max_width=copy_max_width,
            draw=draw,
        ):
            line_h = _draw_left_line(
                draw,
                text=line,
                font=headline_font,
                x=text_margin_x,
                y=cursor_y,
                fill=palette.primary_text,
            )
            cursor_y += line_h + line_gap

    subline_text = (overlay_copy.subline or "").strip()
    if subline_text:
        if overlay_copy.headline:
            cursor_y += max(0, line_gap // 2)
        for line in _wrap_text(
            subline_text,
            font=subline_font,
            max_width=copy_max_width,
            draw=draw,
        ):
            line_h = _draw_left_line(
                draw,
                text=line,
                font=subline_font,
                x=text_margin_x,
                y=cursor_y,
                fill=palette.primary_text,
            )
            cursor_y += line_h + line_gap

    cursor_y = menu_start_y
    for line in menu_lines:
        if menu_plan.menu_align == "left":
            line_h = _draw_left_line(
                draw,
                text=line,
                font=menu_font,
                x=menu_plan.menu_x,
                y=cursor_y,
                fill=palette.accent_text,
            )
        else:
            line_h = _draw_centered_line(
                draw,
                text=line,
                font=menu_font,
                y=cursor_y,
                image_width=width,
                fill=palette.accent_text,
            )
        cursor_y += line_h + line_gap

    menu_end_y = cursor_y

    # 가격 Pill 뱃지 충돌 방지 동적 위치 계산
    if overlay_copy.price_text:
        price_font = _scale_overlay_font(
            image,
            TextOverlayRole.POSTER_PRICE,
            template.price_size_ratio * menu_plan.font_scale,
            tone=tone,
            food_type=food_type,
            variant="poster",
        )
        badge_cx, badge_cy, badge_w, badge_h = _resolve_price_badge_placement(
            width=width,
            menu_lines=menu_lines,
            menu_font=menu_font,
            menu_start_y=menu_start_y,
            menu_end_y=menu_end_y,
            price_text=overlay_copy.price_text,
            price_font=price_font,
            layout=layout,
            template=template,
            draw=draw,
            menu_layout_mode=menu_plan.layout_mode,
            menu_align=menu_plan.menu_align,
            menu_x=menu_plan.menu_x,
        )

        _draw_price_pill_badge(
            draw,
            text=overlay_copy.price_text,
            font=price_font,
            center_x=badge_cx,
            center_y=badge_cy,
            image_width=width,
            palette=palette,
            template=template,
        )

    if overlay_copy.store_name:
        text_width = int(draw.textlength(overlay_copy.store_name, font=store_font))
        ascent, descent = store_font.getmetrics()
        line_height = ascent + descent
        store_x = width - layout.store_margin_right - text_width
        store_y = height - layout.store_margin_bottom - line_height
        store_x, store_y = layout.clamp_store_position(
            x=store_x,
            y=store_y,
            text_width=text_width,
            text_height=line_height,
        )
        draw.text(
            (store_x, store_y),
            overlay_copy.store_name,
            font=store_font,
            fill=palette.store_text,
        )

    return pil_image_to_png_bytes(image.convert("RGB"))


def _apply_reels_bottom_scrim(image: Image.Image) -> Image.Image:
    """릴스 하단 자막 가독성용 어두운 그라데이션."""
    width, height = image.size
    scrim = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(scrim)
    zone_h = int(height * 0.3)

    for offset, y in enumerate(range(height - zone_h, height)):
        fade = (offset + 1) / zone_h
        alpha = int(170 * fade * fade)
        draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    return Image.alpha_composite(image, scrim)


def composite_reels_hook_text(
    image_bytes: bytes,
    hook_copy: ReelsHookCopy,
    *,
    food_type: str | None = None,
) -> bytes:
    image = image_bytes_to_pil(image_bytes).convert("RGBA")
    image = _apply_reels_bottom_scrim(image)
    draw = ImageDraw.Draw(image)

    margin_x = int(image.width * 0.045)
    margin_bottom = int(image.height * 0.038)
    max_text_width = int(image.width * 0.9)

    lead_font = _scale_overlay_font(
        image,
        TextOverlayRole.REELS_HOOK_LEAD,
        0.058,
        food_type=food_type,
        variant="instagram_feed",
    )
    emphasis_font = _scale_overlay_font(
        image,
        TextOverlayRole.REELS_HOOK,
        0.066,
        food_type=food_type,
        variant="instagram_feed",
    )
    stroke_width = max(3, int(image.width * 0.0055))

    lines: list[tuple[str, ImageFont.FreeTypeFont]] = []
    if hook_copy.lead_line:
        lines.append((hook_copy.lead_line, lead_font))
    if hook_copy.emphasis_line:
        for emphasis_line in _wrap_text(
            hook_copy.emphasis_line,
            font=emphasis_font,
            max_width=max_text_width,
            draw=draw,
        ):
            lines.append((emphasis_line, emphasis_font))

    if not lines:
        return image_bytes

    block_height = 0
    line_metrics: list[tuple[str, ImageFont.FreeTypeFont, int]] = []
    for text, font in lines:
        ascent, descent = font.getmetrics()
        line_height = ascent + descent
        line_metrics.append((text, font, line_height))
        block_height += line_height

    gap = max(6, int(image.height * 0.008))
    block_height += gap * (len(lines) - 1)
    cursor_y = image.height - margin_bottom - block_height

    for index, (text, font, line_height) in enumerate(line_metrics):
        _draw_stroked_text(
            draw,
            (margin_x, cursor_y),
            text,
            font=font,
            fill=(255, 255, 255),
            stroke_fill=(0, 0, 0),
            stroke_width=stroke_width,
        )
        cursor_y += line_height
        if index < len(line_metrics) - 1:
            cursor_y += gap

    return pil_image_to_png_bytes(image.convert("RGB"))


def apply_variant_text_overlay(
    image_bytes: bytes,
    *,
    payload: ImageAdRequest,
    variant: ImageVariantType,
) -> bytes:
    food_type = payload.food_type
    try:
        if variant == "instagram_feed":
            return composite_reels_hook_text(
                image_bytes,
                build_reels_overlay_copy(payload),
                food_type=food_type,
            )
        if variant == "poster":
            return composite_poster_text(
                image_bytes,
                build_poster_overlay_copy(payload),
                tone=payload.tone,
                food_type=food_type,
            )
        return image_bytes
    except Exception as exc:
        logger.exception(
            "image_text_overlay_failed | variant={} | food_type={} | error={}",
            variant,
            food_type,
            str(exc),
        )
        return image_bytes
