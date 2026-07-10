"""
인스타 릴스 이미지에 한국어 후킹 자막을 PIL로 합성한다.

포스터 텍스트는 이미지 모델이 디자인과 함께 생성한다.
"""

from __future__ import annotations

from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from app.schemas.image_ad import ImageAdRequest, ImageVariantType
from app.services.pipelines.food_type_prompts import uses_custom_template
from app.utils.font_registry import TextOverlayRole, load_overlay_font
from app.utils.image_bytes import image_bytes_to_pil, pil_image_to_png_bytes
from app.utils.reels_hooks import ReelsHookCopy, resolve_reels_hook_lines


def variant_uses_pil_text_overlay(food_type: str | None, variant: ImageVariantType) -> bool:
    if not food_type or variant != "instagram_feed":
        return False
    return uses_custom_template(food_type, variant)  # type: ignore[arg-type]


def build_reels_overlay_copy(payload: ImageAdRequest) -> ReelsHookCopy:
    return resolve_reels_hook_lines(
        payload.promotion_goal or "",
        store_name=payload.store_name or "",
        menu_name=payload.menu_name or "",
        price_text=payload.price_text or "",
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
    if variant != "instagram_feed":
        return image_bytes

    food_type = payload.food_type
    try:
        return composite_reels_hook_text(
            image_bytes,
            build_reels_overlay_copy(payload),
            food_type=food_type,
        )
    except Exception as exc:
        logger.exception(
            "image_text_overlay_failed | variant={} | food_type={} | error={}",
            variant,
            food_type,
            str(exc),
        )
        return image_bytes
