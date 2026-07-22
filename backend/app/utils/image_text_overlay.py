"""
인스타 릴스·포스터 이미지에 한국어 텍스트를 PIL로 합성한다.

포스터: AI는 배경+음식만 생성, 카피·메뉴명·가격 pill·가게명은 PIL 합성.
       rembg 기반 LayoutSpec으로 배치·배경색·scrim을 적용한다.
릴스: 하단 후킹 자막 PIL 합성.
"""

from __future__ import annotations

import re
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
    apply_template_overrides,
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


def _text_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    stroke_width: int = 0,
) -> tuple[int, int]:
    """렌더링 bbox 기준 텍스트 크기. 한글과 영문 혼용 시 metrics 오차를 피한다."""

    left, top, right, bottom = draw.textbbox(
        (0, 0),
        text,
        font=font,
        anchor="lt",
        stroke_width=stroke_width,
    )
    return max(1, right - left), max(1, bottom - top)


def _fit_poster_font(
    image: Image.Image,
    *,
    role: TextOverlayRole,
    ratio: float,
    text: str,
    max_width: int,
    max_lines: int,
    draw: ImageDraw.ImageDraw,
    tone: str | None,
    food_type: str | None,
) -> tuple[ImageFont.FreeTypeFont, list[str], float]:
    min_ratio = _RATIO_BOUNDS["menu_size_ratio"][0] if role == TextOverlayRole.POSTER_MENU else 0.018
    current_ratio = ratio
    lines: list[str] = []

    for _ in range(_MAX_FONT_SHRINK_STEPS + 1):
        font = _scale_overlay_font(
            image,
            role,
            current_ratio,
            tone=tone,
            food_type=food_type,
            variant="poster",
        )
        lines = _wrap_text(text, font=font, max_width=max_width, draw=draw)
        widest = max((draw.textlength(line, font=font) for line in lines), default=0)
        if len(lines) <= max_lines and widest <= max_width:
            return font, lines, current_ratio
        current_ratio = max(min_ratio, current_ratio * _MENU_FONT_SHRINK_FACTOR)

    return font, lines[:max_lines], current_ratio


def _draw_text_lines(
    draw: ImageDraw.ImageDraw,
    *,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    align: str,
    fill: tuple[int, int, int],
    gap: int,
    stroke_fill: tuple[int, int, int] | None = None,
    stroke_width: int = 0,
) -> tuple[int, int, int]:
    """텍스트 여러 줄을 그리고 (끝 y, 최대 폭, 전체 높이)를 반환한다."""

    cursor_y = y
    max_width = 0
    anchor = "mt" if align == "center" else "lt"
    for line in lines:
        line_width, line_height = _text_box(draw, line, font)
        draw.text(
            (x, cursor_y),
            line,
            font=font,
            fill=fill,
            anchor=anchor,
            stroke_fill=stroke_fill,
            stroke_width=stroke_width,
        )
        cursor_y += line_height + gap
        max_width = max(max_width, line_width)

    if lines:
        cursor_y -= gap
    return cursor_y, max_width, max(0, cursor_y - y)


def _draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    tracking: int,
    fill: tuple[int, int, int] | tuple[int, int, int, int],
    align: str = "left",
) -> tuple[int, int]:
    """Pillow에 없는 자간 제어를 문자 단위 advance로 구현한다."""

    if not text:
        return 0, 0

    advances = [float(draw.textlength(char, font=font)) for char in text]
    total_width = int(sum(advances) + tracking * max(0, len(text) - 1))
    cursor_x = float(x - total_width / 2) if align == "center" else float(x)
    _, text_height = _text_box(draw, text, font)

    for char, advance in zip(text, advances, strict=False):
        draw.text((int(cursor_x), y), char, font=font, fill=fill, anchor="lt")
        cursor_x += advance + tracking
    return total_width, text_height


def _draw_four_point_star(
    draw: ImageDraw.ImageDraw,
    *,
    center: tuple[int, int],
    radius: int,
    fill: tuple[int, int, int, int],
) -> None:
    cx, cy = center
    inner = max(1, int(radius * 0.16))
    points = [
        (cx, cy - radius),
        (cx + inner, cy - inner),
        (cx + radius, cy),
        (cx + inner, cy + inner),
        (cx, cy + radius),
        (cx - inner, cy + inner),
        (cx - radius, cy),
        (cx - inner, cy - inner),
    ]
    draw.polygon(points, fill=fill)


def _draw_poster_ornaments(
    image: Image.Image,
    *,
    template: PosterTemplateSpec,
    palette: PosterPaletteSpec,
) -> Image.Image:
    """템플릿 계열별 인쇄 포스터 장식을 반투명 벡터로 그린다."""

    width, height = image.size
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    accent = (*palette.accent_text, 92)
    muted = (*palette.primary_text, 54)
    margin = max(18, int(width * 0.038))

    if template.composition == "framed":
        draw.rectangle(
            (margin, margin, width - margin, height - margin),
            outline=accent,
            width=max(1, int(width * 0.0022)),
        )
        inner = margin + max(7, int(width * 0.009))
        corner = int(width * 0.070)
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            ox = inner if sx > 0 else width - inner
            oy = inner if sy > 0 else height - inner
            draw.line((ox, oy, ox + sx * corner, oy), fill=muted, width=1)
            draw.line((ox, oy, ox, oy + sy * corner), fill=muted, width=1)

    elif template.composition == "centered":
        for rx, ry, scale in (
            (0.12, 0.115, 0.014),
            (0.87, 0.245, 0.010),
        ):
            _draw_four_point_star(
                draw,
                center=(int(width * rx), int(height * ry)),
                radius=max(4, int(width * scale)),
                fill=accent,
            )
        wave_w = int(width * 0.095)
        wave_h = int(width * 0.035)
        for side_x in (margin, width - margin - wave_w):
            for offset in range(2):
                top = int(height * 0.295) + offset * int(wave_h * 0.52)
                draw.arc(
                    (side_x, top, side_x + wave_w, top + wave_h),
                    start=195,
                    end=345,
                    fill=muted,
                    width=max(1, int(width * 0.0018)),
                )

    else:
        rule_y = int(height * 0.047)
        draw.line(
            (margin, rule_y, width - margin, rule_y),
            fill=muted,
            width=max(1, int(width * 0.0015)),
        )
        circle_r = int(width * 0.115)
        circle_cx = width - margin - circle_r
        circle_cy = int(height * 0.405)
        draw.ellipse(
            (
                circle_cx - circle_r,
                circle_cy - circle_r,
                circle_cx + circle_r,
                circle_cy + circle_r,
            ),
            outline=muted,
            width=max(1, int(width * 0.0015)),
        )

    return Image.alpha_composite(image, overlay)


def _price_component_metrics(
    image: Image.Image,
    *,
    text: str,
    font: ImageFont.FreeTypeFont,
    template: PosterTemplateSpec,
) -> tuple[int, int]:
    draw = ImageDraw.Draw(image)
    text_width, text_height = _text_box(draw, text, font)
    pad_x = max(12, int(image.width * template.badge_pad_x_ratio * 0.72))
    pad_y = max(6, int(image.width * template.badge_pad_y_ratio * 0.54))
    if template.price_style == "stamp":
        pad_x = max(pad_x, int(image.width * 0.026))
        pad_y = max(pad_y, int(image.width * 0.016))
    return text_width + pad_x * 2, text_height + pad_y * 2


def _format_price_text(text: str) -> str:
    stripped = (text or "").strip()
    match = re.fullmatch(r"([0-9][0-9,]*)\s*원", stripped)
    if match is None:
        return stripped
    digits = match.group(1).replace(",", "")
    return f"{int(digits):,}원"


def _draw_price_component(
    image: Image.Image,
    *,
    text: str,
    font: ImageFont.FreeTypeFont,
    center_x: int,
    center_y: int,
    palette: PosterPaletteSpec,
    template: PosterTemplateSpec,
) -> tuple[int, int]:
    """UI pill 대신 라벨, 티켓, 스탬프 세 종류의 가격표를 그린다."""

    draw = ImageDraw.Draw(image)
    text_width, text_height = _text_box(draw, text, font)
    badge_w, badge_h = _price_component_metrics(
        image,
        text=text,
        font=font,
        template=template,
    )
    pad_x = max(12, int(image.width * template.badge_pad_x_ratio * 0.72))
    left = int(center_x - badge_w / 2)
    top = int(center_y - badge_h / 2)
    right = left + badge_w
    bottom = top + badge_h
    outline_w = max(2, int(image.width * template.badge_outline_width_ratio * 0.7))

    if template.price_style == "stamp":
        draw.ellipse((left, top, right, bottom), outline=palette.badge_outline, width=outline_w)
        inset = max(4, outline_w * 2)
        draw.ellipse(
            (left + inset, top + inset, right - inset, bottom - inset),
            outline=palette.badge_outline,
            width=max(1, outline_w // 2),
        )
        draw.text(
            (center_x, center_y),
            text,
            font=font,
            fill=palette.badge_text,
            anchor="mm",
        )
        return badge_w, badge_h

    if template.price_style == "ticket":
        # 가격은 별도의 UI 버튼이 아니라 메뉴명에 붙는 작은 메타 정보로 보이게 한다.
        dot_r = max(2, int(badge_h * 0.055))
        arm = max(8, int(image.width * 0.018))
        for dot_x, direction in ((left + pad_x // 2, -1), (right - pad_x // 2, 1)):
            draw.ellipse(
                (dot_x - dot_r, center_y - dot_r, dot_x + dot_r, center_y + dot_r),
                fill=palette.badge_outline,
            )
            line_end = dot_x + direction * arm
            draw.line(
                (dot_x + direction * (dot_r + 3), center_y, line_end, center_y),
                fill=(*palette.badge_outline, 150),
                width=max(1, outline_w // 2),
            )
        draw.text(
            (center_x, center_y),
            text,
            font=font,
            fill=palette.badge_text,
            anchor="mm",
        )
        return badge_w, badge_h

    line_gap = max(4, int(image.width * 0.006))
    draw.line(
        (left, top + line_gap, right, top + line_gap),
        fill=palette.badge_outline,
        width=outline_w,
    )
    draw.line(
        (left, bottom - line_gap, right, bottom - line_gap),
        fill=palette.badge_outline,
        width=outline_w,
    )
    draw.text(
        (center_x, center_y),
        text,
        font=font,
        fill=palette.badge_text,
        anchor="mm",
    )
    return badge_w, badge_h


def _restore_food_foreground(
    image: Image.Image,
    *,
    source: Image.Image,
    alpha: Image.Image | None,
) -> Image.Image:
    """메인 제목을 음식 뒤로 보내기 위해 원본 foreground를 같은 위치에 다시 덮는다."""

    if alpha is None or alpha.size != image.size or alpha.getbbox() is None:
        return image
    foreground = Image.new("RGBA", image.size, (0, 0, 0, 0))
    foreground.paste(source, (0, 0), alpha)
    return Image.alpha_composite(image, foreground)


def _draw_poster_footer(
    image: Image.Image,
    *,
    store_name: str,
    menu_name: str,
    store_font: ImageFont.FreeTypeFont,
    palette: PosterPaletteSpec,
    template: PosterTemplateSpec,
    layout: PosterLayoutSpec,
) -> None:
    if not store_name:
        return

    draw = ImageDraw.Draw(image)
    margin = max(24, int(image.width * 0.065))
    baseline_y = image.height - max(layout.store_margin_bottom, int(image.height * 0.045))
    _, text_h = _text_box(draw, store_name, store_font)
    text_y = baseline_y - text_h
    store_w, _ = _text_box(draw, store_name, store_font)
    text_x, text_y = layout.clamp_store_position(
        x=margin,
        y=text_y,
        text_width=store_w,
        text_height=text_h,
    )
    rule_y = text_y - max(8, int(image.height * 0.008))
    footer_color = _resolve_footer_color(image, palette.store_text, text_y)
    draw.line(
        (margin, rule_y, image.width - margin, rule_y),
        fill=(*footer_color, 150),
        width=max(1, int(image.width * 0.0015)),
    )
    draw.text((text_x, text_y), store_name, font=store_font, fill=footer_color, anchor="lt")

    footer_font = load_overlay_font(
        TextOverlayRole.POSTER_STORE,
        max(12, int(image.width * 0.019)),
        variant="poster",
    )
    menu_w, _ = _text_box(draw, menu_name, footer_font)
    draw.text(
        (image.width - margin - menu_w, text_y),
        menu_name,
        font=footer_font,
        fill=footer_color,
        anchor="lt",
    )


def _wcag_luminance(rgb: tuple[int, int, int]) -> float:
    channels: list[float] = []
    for value in rgb:
        normalized = value / 255.0
        channels.append(
            normalized / 12.92
            if normalized <= 0.04045
            else ((normalized + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    light = max(_wcag_luminance(a), _wcag_luminance(b))
    dark = min(_wcag_luminance(a), _wcag_luminance(b))
    return (light + 0.05) / (dark + 0.05)


def _resolve_footer_color(
    image: Image.Image,
    preferred: tuple[int, int, int],
    y: int,
) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    xs = [int(image.width * ratio) for ratio in (0.08, 0.22, 0.50, 0.78, 0.92)]
    ys = [max(0, min(image.height - 1, y + offset)) for offset in (-8, 0, 8)]
    samples = [rgb.getpixel((x, sample_y)) for sample_y in ys for x in xs]
    background = tuple(sum(pixel[channel] for pixel in samples) // len(samples) for channel in range(3))
    candidates = (preferred, (42, 34, 28), (246, 240, 228))
    return max(candidates, key=lambda color: _contrast_ratio(color, background))


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
    design_style: str | None = None,
    layout: PosterLayoutSpec | None = None,
) -> bytes:
    """톤에 따라 editorial, centered, framed 구성을 적용하는 포스터 렌더러."""

    image = image_bytes_to_pil(image_bytes).convert("RGBA")
    if layout is None:
        layout = analyze_poster_layout(image.convert("RGB"))

    image = _apply_poster_top_scrim(
        image,
        scrim_height=layout.scrim_height,
        max_alpha=layout.scrim_max_alpha,
    )
    foreground_source = image.copy()
    palette = layout.palette
    template = resolve_poster_template_for_layout(
        tone,
        vlm_overrides=layout.vlm_template_overrides,
    )
    if design_style in {"editorial", "centered", "framed"}:
        price_style = "label" if design_style == "editorial" else "ticket"
        template = apply_template_overrides(
            template,
            {
                "composition": design_style,
                "price_style": price_style,
            },
        )
    image = _draw_poster_ornaments(
        image,
        template=template,
        palette=palette,
    )
    # 장식은 음식 뒤에, 모든 핵심 정보는 음식 앞에 둔다. 세로로 긴 음료에서도
    # 메뉴명이 컵 뒤로 사라지지 않게 하는 레이어 순서다.
    image = _restore_food_foreground(
        image,
        source=foreground_source,
        alpha=(
            layout.foreground_alpha
            if layout.food_bbox is not None and not layout.used_fallback
            else None
        ),
    )
    draw = ImageDraw.Draw(image)

    width, height = image.size
    centered = template.composition == "centered"
    text_margin_x = max(
        30,
        int(width * 0.065),
    )
    copy_max_width = int(width * (0.76 if centered else 0.58))
    menu_max_width = int(
        width
        * (
            0.84
            if centered
            else 0.70
            if template.composition == "editorial"
            else 0.68
        )
    )
    line_gap = max(7, int(height * 0.009))
    align = "center" if centered else "left"
    anchor_x = width // 2 if centered else text_margin_x

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
        TextOverlayRole.POSTER_PRICE,
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
    menu_font, menu_lines, resolved_menu_ratio = _fit_poster_font(
        image,
        role=TextOverlayRole.POSTER_MENU,
        ratio=template.menu_size_ratio,
        text=overlay_copy.menu_name,
        max_width=menu_max_width,
        max_lines=2,
        draw=draw,
        tone=tone,
        food_type=food_type,
    )
    price_font = _scale_overlay_font(
        image,
        TextOverlayRole.POSTER_PRICE,
        template.price_size_ratio * (resolved_menu_ratio / template.menu_size_ratio),
        tone=tone,
        food_type=food_type,
        variant="poster",
    )

    cursor_y = max(
        layout.content_top_y,
        int(height * (0.062 if template.composition == "framed" else 0.055)),
    )
    sticker_text = (overlay_copy.sticker or "").strip()
    if sticker_text:
        _, sticker_h = _draw_tracked_text(
            draw,
            text=sticker_text,
            font=sticker_font,
            x=anchor_x,
            y=cursor_y,
            tracking=max(2, int(width * 0.0045)),
            fill=palette.accent_text,
            align=align,
        )
        cursor_y += sticker_h + max(line_gap, int(height * 0.012))

    if overlay_copy.headline:
        headline_lines = _wrap_text(
            overlay_copy.headline,
            font=headline_font,
            max_width=copy_max_width,
            draw=draw,
        )
        cursor_y, _, _ = _draw_text_lines(
            draw,
            lines=headline_lines,
            font=headline_font,
            x=anchor_x,
            y=cursor_y,
            align=align,
            fill=palette.primary_text,
            gap=max(3, line_gap // 2),
        )
        cursor_y += max(line_gap, int(height * 0.010))

    subline_text = (overlay_copy.subline or "").strip()
    if subline_text:
        subline_lines = _wrap_text(
            subline_text,
            font=subline_font,
            max_width=copy_max_width,
            draw=draw,
        )
        cursor_y, _, _ = _draw_text_lines(
            draw,
            lines=subline_lines,
            font=subline_font,
            x=anchor_x,
            y=cursor_y,
            align=align,
            fill=palette.primary_text,
            gap=max(2, line_gap // 3),
        )

    cursor_y += max(line_gap, int(height * template.headline_menu_gap_ratio))
    menu_line_gap = max(4, int(height * 0.004))
    measured_menu_h = sum(_text_box(draw, line, menu_font)[1] for line in menu_lines)
    measured_menu_h += menu_line_gap * max(0, len(menu_lines) - 1)
    food_top = layout.food_visual_top
    if food_top is None and layout.food_bbox:
        food_top = layout.food_bbox[1]

    menu_start_y = cursor_y
    if template.composition == "editorial" and food_top is not None:
        overlap_target = int(
            food_top - measured_menu_h * (1.0 - template.menu_overlap_ratio)
        )
        menu_start_y = max(cursor_y, overlap_target)

    menu_overlaps_food = bool(
        food_top is not None and menu_start_y + measured_menu_h > food_top
    )
    menu_end_y, menu_drawn_width, menu_block_height = _draw_text_lines(
        draw,
        lines=menu_lines,
        font=menu_font,
        x=anchor_x,
        y=menu_start_y,
        align=align,
        fill=palette.accent_text,
        gap=menu_line_gap,
        stroke_fill=palette.primary_stroke if menu_overlaps_food else None,
        stroke_width=max(1, int(width * 0.0014)) if menu_overlaps_food else 0,
    )

    if overlay_copy.price_text:
        price_draw = ImageDraw.Draw(image)
        price_text = _format_price_text(overlay_copy.price_text)
        badge_w, badge_h = _price_component_metrics(
            image,
            text=price_text,
            font=price_font,
            template=template,
        )
        lockup_gap = max(12, int(height * 0.012))

        if template.composition == "centered":
            if template.price_style == "stamp":
                badge_cx = int(width // 2 + min(menu_drawn_width * 0.24, width * 0.16))
                lockup_gap = max(10, int(height * 0.008))
            else:
                badge_cx = width // 2
            badge_cy = int(menu_end_y + lockup_gap + badge_h / 2)
        else:
            content_right = width - text_margin_x
            menu_right = anchor_x + menu_drawn_width
            price_left = content_right - badge_w
            same_row_gap = max(18, int(width * 0.022))
            if price_left >= menu_right + same_row_gap:
                badge_cx = price_left + badge_w // 2
                badge_cy = int(menu_start_y + menu_block_height / 2)
                connector_left = menu_right + same_row_gap // 2
                connector_right = price_left - same_row_gap // 2
                if connector_right > connector_left:
                    price_draw.line(
                        (connector_left, badge_cy, connector_right, badge_cy),
                        fill=(*palette.badge_outline, 105),
                        width=max(1, int(width * 0.0012)),
                    )
            else:
                badge_cx = text_margin_x + badge_w // 2
                badge_cy = int(menu_end_y + lockup_gap + badge_h / 2)

        _draw_price_component(
            image,
            text=price_text,
            font=price_font,
            center_x=badge_cx,
            center_y=badge_cy,
            palette=palette,
            template=template,
        )

    _draw_poster_footer(
        image,
        store_name=overlay_copy.store_name,
        menu_name=overlay_copy.menu_name,
        store_font=store_font,
        palette=palette,
        template=template,
        layout=layout,
    )

    logger.info(
        "poster_design_applied | composition={} | price_style={} | menu_ratio={:.3f} | "
        "menu_width={} | foreground_layered={}",
        template.composition,
        template.price_style,
        resolved_menu_ratio,
        menu_drawn_width,
        layout.foreground_alpha is not None and not layout.used_fallback,
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
                design_style=payload.layout_type,
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
