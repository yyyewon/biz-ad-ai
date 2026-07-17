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
from app.utils.poster_layout import PosterLayoutSpec, PosterPaletteSpec, analyze_poster_layout
from app.utils.poster_taglines import resolve_poster_headline
from app.utils.reels_hooks import ReelsHookCopy, resolve_reels_hook_lines


@dataclass(frozen=True)
class PosterOverlayCopy:
    headline: str
    menu_name: str
    price_text: str
    store_name: str


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
    headline = (payload.headline or "").strip()
    if not headline:
        headline = resolve_poster_headline(
            payload.promotion_goal or "",
            payload.tone,
        )

    return PosterOverlayCopy(
        headline=headline,
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
    stroke_fill: tuple[int, int, int],
    stroke_width: int,
) -> int:
    x = _centered_x(draw, text, font, image_width)
    _draw_stroked_text(
        draw,
        (x, y),
        text,
        font=font,
        fill=fill,
        stroke_fill=stroke_fill,
        stroke_width=stroke_width,
    )
    ascent, descent = font.getmetrics()
    return ascent + descent


def _draw_price_pill_badge(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    font: ImageFont.FreeTypeFont,
    center_x: int,
    center_y: int,
    image_width: int,
    palette: PosterPaletteSpec,
) -> None:
    text_width = int(draw.textlength(text, font=font))
    ascent, descent = font.getmetrics()
    text_height = ascent + descent

    pad_x = max(10, int(image_width * 0.028))
    pad_y = max(6, int(image_width * 0.012))
    badge_w = text_width + pad_x * 2
    badge_h = text_height + pad_y * 2
    radius = badge_h // 2

    left = int(center_x - badge_w / 2)
    top = int(center_y - badge_h / 2)
    bbox = (left, top, left + badge_w, top + badge_h)
    outline_width = max(2, int(image_width * 0.0035))

    draw.rounded_rectangle(
        bbox,
        radius=radius,
        outline=palette.badge_outline,
        width=outline_width,
    )

    text_x = left + pad_x
    text_y = top + (badge_h - text_height) // 2
    draw.text((text_x, text_y), text, font=font, fill=palette.badge_text)


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
    draw = ImageDraw.Draw(image)

    width, height = image.size
    max_text_width = layout.max_text_width
    line_gap = layout.line_gap
    stroke_width = layout.stroke_width

    headline_font = _scale_overlay_font(
        image,
        TextOverlayRole.POSTER_HEADLINE,
        0.038,
        tone=tone,
        food_type=food_type,
        variant="poster",
    )
    menu_font = _scale_overlay_font(
        image,
        TextOverlayRole.POSTER_MENU,
        0.078,
        tone=tone,
        food_type=food_type,
        variant="poster",
    )
    price_font = _scale_overlay_font(
        image,
        TextOverlayRole.POSTER_PRICE,
        0.034,
        tone=tone,
        food_type=food_type,
        variant="poster",
    )
    store_font = _scale_overlay_font(
        image,
        TextOverlayRole.POSTER_STORE,
        0.036,
        tone=tone,
        food_type=food_type,
        variant="poster",
    )

    cursor_y = layout.content_top_y
    menu_start_y = cursor_y

    if overlay_copy.headline:
        for line in _wrap_text(
            overlay_copy.headline,
            font=headline_font,
            max_width=max_text_width,
            draw=draw,
        ):
            line_h = _draw_centered_line(
                draw,
                text=line,
                font=headline_font,
                y=cursor_y,
                image_width=width,
                fill=palette.primary_text,
                stroke_fill=palette.primary_stroke,
                stroke_width=max(1, stroke_width - 1),
            )
            cursor_y += line_h + line_gap

    menu_start_y = cursor_y
    menu_lines = _wrap_text(
        overlay_copy.menu_name,
        font=menu_font,
        max_width=max_text_width,
        draw=draw,
    )
    for line in menu_lines:
        line_h = _draw_centered_line(
            draw,
            text=line,
            font=menu_font,
            y=cursor_y,
            image_width=width,
            fill=palette.primary_text,
            stroke_fill=palette.primary_stroke,
            stroke_width=stroke_width,
        )
        cursor_y += line_h + line_gap

    menu_end_y = cursor_y

    if overlay_copy.price_text:
        badge_cx = layout.price_badge_cx
        badge_cy = int((menu_start_y + menu_end_y) / 2)
        if badge_cy < layout.price_badge_cy_hint:
            badge_cy = layout.price_badge_cy_hint

        pad_x = max(10, int(width * 0.028))
        pad_y = max(6, int(width * 0.012))
        text_width = int(draw.textlength(overlay_copy.price_text, font=price_font))
        ascent, descent = price_font.getmetrics()
        text_height = ascent + descent
        badge_w = text_width + pad_x * 2
        badge_h = text_height + pad_y * 2
        badge_cx, badge_cy = layout.clamp_price_badge_center(
            center_x=badge_cx,
            center_y=badge_cy,
            badge_width=badge_w,
            badge_height=badge_h,
        )

        _draw_price_pill_badge(
            draw,
            text=overlay_copy.price_text,
            font=price_font,
            center_x=badge_cx,
            center_y=badge_cy,
            image_width=width,
            palette=palette,
        )

    if overlay_copy.store_name:
        store_stroke = max(2, int(width * 0.004))
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
        _draw_stroked_text(
            draw,
            (store_x, store_y),
            overlay_copy.store_name,
            font=store_font,
            fill=palette.store_text,
            stroke_fill=palette.store_stroke,
            stroke_width=store_stroke,
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
