"""
인스타 릴스·포스터 이미지에 한국어 텍스트를 PIL로 합성한다.

포스터: AI는 배경+음식만 생성, 카피·메뉴명·가격 pill·가게명은 PIL 합성.
       글자색은 생성 이미지 상단/하단 영역 색을 샘플링해 배경과 조화되게 맞춘다.
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
from app.utils.poster_taglines import resolve_poster_headline_from_purpose
from app.utils.reels_hooks import ReelsHookCopy, resolve_reels_hook_lines


@dataclass(frozen=True)
class PosterOverlayCopy:
    headline: str
    menu_name: str
    price_text: str
    store_name: str


@dataclass(frozen=True)
class _PosterPalette:
    primary_text: tuple[int, int, int]
    store_text: tuple[int, int, int]
    store_stroke: tuple[int, int, int]
    badge_outline: tuple[int, int, int]
    badge_text: tuple[int, int, int]


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
        headline = resolve_poster_headline_from_purpose(payload.promotion_goal or "")

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
    food_type: str | None = None,
    variant: str | None = None,
) -> ImageFont.FreeTypeFont:
    size = max(12, int(image.width * ratio))
    return load_overlay_font(role, size, food_type=food_type, variant=variant)


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


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _sample_region_mean_rgb(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    width, height = image.size
    left = max(0, min(width, box[0]))
    top = max(0, min(height, box[1]))
    right = max(left + 1, min(width, box[2]))
    bottom = max(top + 1, min(height, box[3]))

    crop = image.crop((left, top, right, bottom)).convert("RGB")
    pixels = list(crop.getdata())
    if not pixels:
        return (120, 80, 55)

    total_r = total_g = total_b = 0
    for r, g, b in pixels:
        total_r += r
        total_g += g
        total_b += b
    count = len(pixels)
    return (total_r // count, total_g // count, total_b // count)


def _harmonious_text_color(background_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    r, g, b = background_rgb
    if _relative_luminance(background_rgb) > 145:
        return (
            max(20, int(r * 0.42)),
            max(20, int(g * 0.42)),
            max(20, int(b * 0.42)),
        )
    return (245, 240, 232)


def _contrast_store_colors(background_rgb: tuple[int, int, int]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    if _relative_luminance(background_rgb) > 120:
        return (30, 30, 30), (255, 255, 255)
    return (255, 255, 255), (0, 0, 0)


def _resolve_poster_palette(image: Image.Image) -> _PosterPalette:
    width, height = image.size
    top_bg = _sample_region_mean_rgb(
        image,
        (
            int(width * 0.12),
            int(height * 0.03),
            int(width * 0.88),
            int(height * 0.34),
        ),
    )
    bottom_right_bg = _sample_region_mean_rgb(
        image,
        (
            int(width * 0.52),
            int(height * 0.84),
            width,
            height,
        ),
    )

    primary = _harmonious_text_color(top_bg)
    store_fill, store_stroke = _contrast_store_colors(bottom_right_bg)
    return _PosterPalette(
        primary_text=primary,
        store_text=store_fill,
        store_stroke=store_stroke,
        badge_outline=primary,
        badge_text=primary,
    )


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
    palette: _PosterPalette,
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
    food_type: str | None = None,
) -> bytes:
    """
    포스터 PIL 합성:
    - 상단 중앙: 카피(작게) + 메뉴명(크게)
    - 우측: pill 가격 뱃지
    - 하단 우측: 가게명
    - 글자색: 이미지 상단/하단 샘플링 기반
    """
    image = image_bytes_to_pil(image_bytes).convert("RGBA")
    palette = _resolve_poster_palette(image.convert("RGB"))
    draw = ImageDraw.Draw(image)

    width, height = image.size
    margin_top = int(height * 0.045)
    max_text_width = int(width * 0.88)
    line_gap = max(6, int(height * 0.012))
    stroke_width = max(1, int(width * 0.003))

    headline_font = _scale_overlay_font(
        image,
        TextOverlayRole.POSTER_HEADLINE,
        0.038,
        food_type=food_type,
        variant="poster",
    )
    menu_font = _scale_overlay_font(
        image,
        TextOverlayRole.POSTER_MENU,
        0.078,
        food_type=food_type,
        variant="poster",
    )
    price_font = _scale_overlay_font(
        image,
        TextOverlayRole.POSTER_PRICE,
        0.034,
        food_type=food_type,
        variant="poster",
    )
    store_font = _scale_overlay_font(
        image,
        TextOverlayRole.POSTER_STORE,
        0.036,
        food_type=food_type,
        variant="poster",
    )

    cursor_y = margin_top
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
                stroke_fill=(255, 255, 255),
                stroke_width=max(1, stroke_width - 1),
            )
            cursor_y += line_h + line_gap
    # 메뉴명이 지나치게 길어 3줄 이상 넘어가면 폰트 사이즈 자동 다운스케일링
    menu_text = overlay_copy.menu_name
    menu_lines = _wrap_text(menu_text, font=menu_font, max_width=max_text_width, draw=draw)
    
    while len(menu_lines) > 2 and menu_ratio > 0.05:
        menu_ratio -= 0.008
        menu_font = _scale_overlay_font(
            image,
            TextOverlayRole.POSTER_MENU,
            menu_ratio,
            food_type=food_type,
            variant="poster",
        )
        menu_lines = _wrap_text(menu_text, font=menu_font, max_width=max_text_width, draw=draw)

    menu_start_y = cursor_y

    max_menu_line_w = 0

    for line in menu_lines:
        line_w = int(draw.textlength(line, font=menu_font))
        if line_w > max_menu_line_w:
            max_menu_line_w = line_w

        line_h = _draw_centered_line(
            draw,
            text=line,
            font=menu_font,
            y=cursor_y,
            image_width=width,
            fill=palette.primary_text,
            stroke_fill=(255, 255, 255),
            stroke_width=stroke_width,
        )
        cursor_y += line_h + line_gap

    menu_end_y = cursor_y

    # 가격 Pill 뱃지 충돌 방지 동적 위치 계산
    if overlay_copy.price_text:
        # 메뉴판의 우측 끝 절대 좌표 계산 (중앙 정렬이므로)
        menu_max_right = (width + max_menu_line_w) // 2
        
        # 가격 텍스트 가로 길이 측정 및 뱃지 여유 폭 예측
        price_text_w = int(draw.textlength(overlay_copy.price_text, font=price_font))
        estimated_pill_w = price_text_w + int(width * 0.06) 

        # 메뉴 우측 끝과 가격 배지가 충돌하는지 검사 (여유 마진 92% 기준)
        if menu_max_right + (estimated_pill_w // 2) > int(width * 0.92):
            # [Case A] 메뉴가 너무 길어 우측 배지와 겹칠 때 -> 메뉴 아래쪽 중앙에 배치
            badge_cx = width // 2
            badge_cy = menu_end_y + int(height * 0.02)
            # 배지가 아래로 내려왔으므로 가이드라인 하한선 배치 스킵하고 고정 마진 확보
        else:
            # [Case B] 우측에 여유가 있을 때 -> 기존처럼 우측에 배치하되 메뉴 길이에 맞춰 밀어내기
            badge_cx = max(int(width * 0.76), menu_max_right + (estimated_pill_w // 2) + int(width * 0.02))
            badge_cy = int((menu_start_y + menu_end_y) / 2)
            if badge_cy < int(height * 0.12):
                badge_cy = int(height * 0.16)

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
        margin_right = int(width * 0.055)
        margin_bottom = int(height * 0.042)
        store_stroke = max(2, int(width * 0.004))
        text_width = int(draw.textlength(overlay_copy.store_name, font=store_font))
        ascent, descent = store_font.getmetrics()
        line_height = ascent + descent
        store_x = width - margin_right - text_width
        store_y = height - margin_bottom - line_height
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
