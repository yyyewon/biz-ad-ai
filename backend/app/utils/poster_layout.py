"""
포스터 PIL 합성용 레이아웃 분석.

rembg로 음식 전경 mask/bbox를 추정하고, 텍스트 배치·배경 기반 색·scrim을
LayoutSpec으로 반환한다. 분석 실패 시 고정 비율 fallback을 쓴다.
"""

from __future__ import annotations

import colorsys
import io
import threading
from dataclasses import dataclass

from loguru import logger
from PIL import Image

_rembg_session = None
_rembg_lock = threading.Lock()

# 포스터 상단 텍스트 / 하단 음식 hero 가정 (AI 프롬프트와 동기화)
_FALLBACK_CONTENT_TOP_RATIO = 0.045
_FALLBACK_PRICE_CX_RATIO = 0.76
_FALLBACK_PRICE_CY_RATIO = 0.16
_FALLBACK_STORE_MARGIN_RIGHT_RATIO = 0.055
_FALLBACK_STORE_MARGIN_BOTTOM_RATIO = 0.042
_FALLBACK_MAX_TEXT_WIDTH_RATIO = 0.88
_FALLBACK_LINE_GAP_RATIO = 0.012
_FALLBACK_STROKE_WIDTH_RATIO = 0.003

_MIN_FOOD_AREA_RATIO = 0.04
_MAX_FOOD_AREA_RATIO = 0.88
_FOOD_TOP_PADDING_RATIO = 0.02
_PRICE_FOOD_PADDING_RATIO = 0.04
_TEXT_ZONE_TOP_RATIO = 0.03
_TEXT_ZONE_BIAS_TOWARD_FOOD = 0.62
_PRICE_SHOULDER_TOP_RATIO = 0.08
_PRICE_SHOULDER_OVERLAP_RATIO = 0.35

_FOREGROUND_ALPHA_THRESHOLD = 128
_SCRIM_COMPLEXITY_THRESHOLD = 22.0
_SCRIM_MAX_ALPHA_CAP = 150


@dataclass(frozen=True)
class PosterPaletteSpec:
    """포스터 텍스트·pill 색상."""

    primary_text: tuple[int, int, int]
    primary_stroke: tuple[int, int, int]
    store_text: tuple[int, int, int]
    store_stroke: tuple[int, int, int]
    badge_outline: tuple[int, int, int]
    badge_text: tuple[int, int, int]


@dataclass(frozen=True)
class PosterLayoutSpec:
    """포스터 텍스트 합성에 필요한 배치·색·scrim 파라미터."""

    width: int
    height: int
    food_bbox: tuple[int, int, int, int] | None
    content_top_y: int
    text_zone_bottom: int | None
    max_text_width: int
    line_gap: int
    stroke_width: int
    price_badge_cx: int
    price_badge_cy_hint: int
    store_margin_right: int
    store_margin_bottom: int
    palette: PosterPaletteSpec
    scrim_height: int
    scrim_max_alpha: int
    used_fallback: bool
    vlm_template: "PosterTemplateSpec | None" = None

    def resolve_text_block_start_y(self, block_height: int) -> int:
        """음식 위 상단 존 안에서 문구+메뉴명 블록 시작 Y를 계산한다."""

        margin_top = max(self.content_top_y, int(self.height * _TEXT_ZONE_TOP_RATIO))
        zone_bottom = self.text_zone_bottom
        if zone_bottom is None and self.food_bbox:
            zone_bottom = self.food_bbox[1] - max(8, int(self.height * _FOOD_TOP_PADDING_RATIO))
        if zone_bottom is None:
            zone_bottom = int(self.height * 0.34)

        zone_bottom = min(zone_bottom, self.height)
        zone_height = max(0, zone_bottom - margin_top)
        min_block = max(1, block_height)
        if zone_height <= min_block:
            return margin_top

        slack = zone_height - min_block
        offset = int(slack * (1.0 - _TEXT_ZONE_BIAS_TOWARD_FOOD))
        return margin_top + offset

    def clamp_price_badge_center(
        self,
        *,
        center_x: int,
        center_y: int,
        badge_width: int,
        badge_height: int,
    ) -> tuple[int, int]:
        """가격 pill이 음식 bbox와 겹치지 않도록 중심 좌표를 조정한다."""

        half_w = badge_width // 2
        half_h = badge_height // 2
        cx = max(half_w, min(self.width - half_w, center_x))
        cy = max(self.content_top_y + half_h, min(self.height - half_h, center_y))

        if not self.food_bbox:
            return cx, cy

        left, top, right, bottom = self.food_bbox
        pad = max(4, int(self.width * _PRICE_FOOD_PADDING_RATIO))
        food_box = (left - pad, top - pad, right + pad, bottom + pad)

        if not _boxes_overlap(
            (cx - half_w, cy - half_h, cx + half_w, cy + half_h),
            food_box,
        ):
            return cx, cy

        candidate_cx = max(half_w, left - pad - half_w)
        candidate_box = (
            candidate_cx - half_w,
            cy - half_h,
            candidate_cx + half_w,
            cy + half_h,
        )
        if not _boxes_overlap(candidate_box, food_box):
            return candidate_cx, cy

        candidate_cy = max(self.content_top_y + half_h, top - pad - half_h)
        return cx, candidate_cy

    def resolve_price_badge_food_top_right(
        self,
        *,
        badge_width: int,
        badge_height: int,
    ) -> tuple[int, int]:
        """가격 pill을 음식 bbox 우측 상단에 붙인다 (캔버스 밖으로만 보정)."""

        margin = max(12, int(self.width * 0.04))
        half_w = badge_width // 2
        half_h = badge_height // 2

        if not self.food_bbox:
            return self.clamp_price_badge_center(
                center_x=self.price_badge_cx,
                center_y=self.price_badge_cy_hint,
                badge_width=badge_width,
                badge_height=badge_height,
            )

        _, top, right, bottom = self.food_bbox
        food_height = max(1, bottom - top)
        pad_y = max(4, int(food_height * 0.04))

        # 잔 어깨(shoulder): 상단에서 약간 아래, 우측은 음식에 30~40% 겹침
        badge_top = int(top + food_height * _PRICE_SHOULDER_TOP_RATIO) + pad_y
        badge_left = int(right - badge_width * _PRICE_SHOULDER_OVERLAP_RATIO)

        badge_left = max(margin, min(self.width - badge_width - margin, badge_left))
        badge_top = max(self.content_top_y, min(self.height - badge_height - margin, badge_top))

        badge_cx = int(badge_left + badge_width / 2)
        badge_cy = int(badge_top + badge_height / 2)

        badge_cx = max(half_w + margin, min(self.width - half_w - margin, badge_cx))
        badge_cy = max(half_h + margin, min(self.height - half_h - margin, badge_cy))
        return badge_cx, badge_cy

    def clamp_store_position(
        self,
        *,
        x: int,
        y: int,
        text_width: int,
        text_height: int,
    ) -> tuple[int, int]:
        """가게명이 음식과 겹치면 위로 밀어 낸다."""

        if not self.food_bbox:
            return x, y

        text_box = (x, y, x + text_width, y + text_height)
        if not _boxes_overlap(text_box, self.food_bbox):
            return x, y

        _, top, _, _ = self.food_bbox
        pad = max(6, int(self.height * 0.012))
        return x, max(self.content_top_y, top - pad - text_height)


def analyze_poster_layout(
    image: Image.Image,
    *,
    layout_mode: str = "single",
) -> PosterLayoutSpec:
    """
    포스터 이미지에서 음식 bbox·배경 색·scrim을 추정해 LayoutSpec을 반환한다.

    layout_mode는 현재 single만 지원한다. multi는 Phase 5에서 확장한다.
    """

    if layout_mode != "single":
        logger.warning(
            "poster_layout_unsupported_mode | mode={} | fallback=single",
            layout_mode,
        )

    rgb_image = image.convert("RGB")
    width, height = rgb_image.size

    alpha: Image.Image | None = None
    food_bbox: tuple[int, int, int, int] | None = None

    try:
        alpha = _detect_foreground_alpha(rgb_image)
        food_bbox = alpha.getbbox()
    except Exception as exc:
        logger.warning(
            "poster_layout_rembg_failed | error={} | using_fallback=true",
            str(exc),
        )
        spec = _build_fallback_spec(rgb_image, food_bbox=None, alpha=None)
        return _apply_vlm_overrides(spec, rgb_image)

    if food_bbox is None:
        logger.info("poster_layout_no_food_bbox | using_fallback=true")
        spec = _build_fallback_spec(rgb_image, food_bbox=None, alpha=alpha)
        return _apply_vlm_overrides(spec, rgb_image)

    if not _is_valid_food_bbox(food_bbox, width, height):
        logger.info(
            "poster_layout_invalid_food_bbox | bbox={} | using_fallback=true",
            food_bbox,
        )
        spec = _build_fallback_spec(rgb_image, food_bbox=None, alpha=alpha)
        return _apply_vlm_overrides(spec, rgb_image)

    spec = _build_spec_from_food_bbox(rgb_image, food_bbox, alpha=alpha)
    spec = _apply_vlm_overrides(spec, rgb_image)
    logger.info(
        "poster_layout_applied | used_fallback={} | food_bbox={} | scrim_alpha={} | vlm_enabled={}",
        spec.used_fallback,
        spec.food_bbox,
        spec.scrim_max_alpha,
        _is_vlm_enabled(),
    )
    return spec


def _is_vlm_enabled() -> bool:
    try:
        from app.utils.poster_vlm import is_poster_vlm_enabled

        return is_poster_vlm_enabled()
    except ImportError:
        return False


def _apply_vlm_overrides(spec: PosterLayoutSpec, image: Image.Image) -> PosterLayoutSpec:
    """VLM 디자인 힌트가 있으면 palette·배치·scrim만 덮어쓴다. food bbox는 유지."""

    try:
        from app.utils.poster_vlm import analyze_poster_design_with_vlm, is_poster_vlm_enabled
    except ImportError:
        return spec

    if not is_poster_vlm_enabled():
        return spec

    hints = analyze_poster_design_with_vlm(image)
    if hints is None:
        logger.info("poster_vlm_skipped | reason=disabled_or_failed | using_rules_palette=true")
        return spec

    merged_palette, palette_used_rules = _reconcile_vlm_palette(
        hints.palette,
        rules_palette=spec.palette,
        image=image,
        food_bbox=spec.food_bbox,
    )
    if palette_used_rules:
        logger.info("poster_vlm_palette_reconciled | used_rules_fallback=true")

    scrim_max_alpha = (
        hints.scrim_max_alpha if hints.scrim_max_alpha is not None else spec.scrim_max_alpha
    )
    if palette_used_rules and scrim_max_alpha < 60:
        scrim_max_alpha = max(scrim_max_alpha, 60)

    return PosterLayoutSpec(
        width=spec.width,
        height=spec.height,
        food_bbox=spec.food_bbox,
        content_top_y=spec.content_top_y,
        text_zone_bottom=spec.text_zone_bottom,
        max_text_width=spec.max_text_width,
        line_gap=spec.line_gap,
        stroke_width=spec.stroke_width,
        price_badge_cx=hints.price_badge_cx if hints.price_badge_cx is not None else spec.price_badge_cx,
        price_badge_cy_hint=(
            hints.price_badge_cy_hint
            if hints.price_badge_cy_hint is not None
            else spec.price_badge_cy_hint
        ),
        store_margin_right=spec.store_margin_right,
        store_margin_bottom=spec.store_margin_bottom,
        palette=merged_palette,
        scrim_height=hints.scrim_height if hints.scrim_height is not None else spec.scrim_height,
        scrim_max_alpha=scrim_max_alpha,
        used_fallback=spec.used_fallback,
        vlm_template=hints.template,
    )


def _reconcile_vlm_palette(
    vlm_palette: PosterPaletteSpec,
    *,
    rules_palette: PosterPaletteSpec,
    image: Image.Image,
    food_bbox: tuple[int, int, int, int] | None,
) -> tuple[PosterPaletteSpec, bool]:
    """VLM palette를 배경 대비·퇴화 출력 기준으로 보정한다."""

    width, height = image.size
    top_bottom = int(height * 0.34)
    if food_bbox:
        top_bottom = min(top_bottom, max(int(height * 0.12), food_bbox[1] - 8))

    top_bg = _sample_background_mean_rgb(
        image,
        None,
        (int(width * 0.12), int(height * 0.03), int(width * 0.88), top_bottom),
    )
    bottom_bg = _sample_background_mean_rgb(
        image,
        None,
        (int(width * 0.52), int(height * 0.84), width, height),
    )

    if _is_degenerate_vlm_palette(vlm_palette):
        return rules_palette, True

    used_rules = False

    primary_text = vlm_palette.primary_text
    primary_stroke = vlm_palette.primary_stroke
    if not _text_bg_contrast_ok(primary_text, top_bg):
        primary_text = rules_palette.primary_text
        primary_stroke = rules_palette.primary_stroke
        used_rules = True
    elif not _text_bg_contrast_ok(primary_stroke, top_bg):
        primary_stroke = _primary_stroke_color(top_bg, primary_text)

    store_text = vlm_palette.store_text
    store_stroke = vlm_palette.store_stroke
    if not _text_bg_contrast_ok(store_text, bottom_bg):
        store_text = rules_palette.store_text
        store_stroke = rules_palette.store_stroke
        used_rules = True
    elif not _text_bg_contrast_ok(store_stroke, bottom_bg):
        store_stroke = _primary_stroke_color(bottom_bg, store_text)

    badge_text = vlm_palette.badge_text
    badge_outline = vlm_palette.badge_outline
    if not _text_bg_contrast_ok(badge_text, top_bg):
        badge_text = primary_text
        used_rules = True
    if not _text_bg_contrast_ok(badge_outline, top_bg):
        badge_outline = primary_stroke if _text_bg_contrast_ok(primary_stroke, top_bg) else primary_text
        used_rules = True

    return (
        _ensure_palette_readability(
            PosterPaletteSpec(
                primary_text=primary_text,
                primary_stroke=primary_stroke,
                store_text=store_text,
                store_stroke=store_stroke,
                badge_text=badge_text,
                badge_outline=badge_outline,
            ),
            top_bg=top_bg,
            bottom_bg=bottom_bg,
        ),
        used_rules,
    )


def _is_degenerate_vlm_palette(palette: PosterPaletteSpec) -> bool:
    """VLM이 예시/기본값만 복사한 palette인지 검사."""

    fields = (
        palette.primary_text,
        palette.primary_stroke,
        palette.store_text,
        palette.store_stroke,
        palette.badge_text,
        palette.badge_outline,
    )
    if all(all(channel >= 250 for channel in rgb) for rgb in fields):
        return True
    return len(set(fields)) == 1


def _text_bg_contrast_ok(
    text_rgb: tuple[int, int, int],
    background_rgb: tuple[int, int, int],
    *,
    min_delta: float = 42.0,
) -> bool:
    return abs(_relative_luminance(text_rgb) - _relative_luminance(background_rgb)) >= min_delta


def _get_rembg_session():
    global _rembg_session

    with _rembg_lock:
        if _rembg_session is None:
            from rembg import new_session

            _rembg_session = new_session("u2net")
        return _rembg_session


def _detect_foreground_alpha(image: Image.Image) -> Image.Image:
    from rembg import remove

    rgb_image = image.convert("RGB")
    buffer = io.BytesIO()
    rgb_image.save(buffer, format="PNG")

    session = _get_rembg_session()
    output_bytes = remove(buffer.getvalue(), session=session)
    rgba = Image.open(io.BytesIO(output_bytes)).convert("RGBA")
    return rgba.split()[-1]


def _is_valid_food_bbox(
    bbox: tuple[int, int, int, int],
    width: int,
    height: int,
) -> bool:
    left, top, right, bottom = bbox
    box_w = max(0, right - left)
    box_h = max(0, bottom - top)
    if box_w < 8 or box_h < 8:
        return False

    image_area = width * height
    box_area = box_w * box_h
    ratio = box_area / image_area if image_area else 0.0
    return _MIN_FOOD_AREA_RATIO <= ratio <= _MAX_FOOD_AREA_RATIO


def _build_fallback_spec(
    image: Image.Image,
    *,
    food_bbox: tuple[int, int, int, int] | None,
    alpha: Image.Image | None,
) -> PosterLayoutSpec:
    width, height = image.size
    palette = _build_palette(image, alpha=alpha, food_bbox=food_bbox)
    scrim_height, scrim_alpha = _compute_scrim(
        image,
        alpha=alpha,
        food_bbox=food_bbox,
        top_text_bottom=int(height * 0.34),
    )

    return PosterLayoutSpec(
        width=width,
        height=height,
        food_bbox=food_bbox,
        content_top_y=int(height * _FALLBACK_CONTENT_TOP_RATIO),
        text_zone_bottom=int(height * 0.34) if food_bbox is None else (
            food_bbox[1] - max(8, int(height * _FOOD_TOP_PADDING_RATIO))
        ),
        max_text_width=int(width * _FALLBACK_MAX_TEXT_WIDTH_RATIO),
        line_gap=max(6, int(height * _FALLBACK_LINE_GAP_RATIO)),
        stroke_width=max(1, int(width * _FALLBACK_STROKE_WIDTH_RATIO)),
        price_badge_cx=int(width * _FALLBACK_PRICE_CX_RATIO),
        price_badge_cy_hint=int(height * _FALLBACK_PRICE_CY_RATIO),
        store_margin_right=int(width * _FALLBACK_STORE_MARGIN_RIGHT_RATIO),
        store_margin_bottom=int(height * _FALLBACK_STORE_MARGIN_BOTTOM_RATIO),
        palette=palette,
        scrim_height=scrim_height,
        scrim_max_alpha=scrim_alpha,
        used_fallback=True,
    )


def _build_spec_from_food_bbox(
    image: Image.Image,
    food_bbox: tuple[int, int, int, int],
    *,
    alpha: Image.Image | None,
) -> PosterLayoutSpec:
    width, height = image.size
    fallback = _build_fallback_spec(image, food_bbox=food_bbox, alpha=alpha)
    _, food_top, food_right, _ = food_bbox

    content_top_y = fallback.content_top_y
    text_bottom_limit = max(
        content_top_y + int(height * 0.08),
        food_top - max(8, int(height * _FOOD_TOP_PADDING_RATIO)),
    )

    if text_bottom_limit <= content_top_y + int(height * 0.05):
        return fallback

    text_zone_bottom = text_bottom_limit
    price_cx = fallback.price_badge_cx
    if food_right > int(width * 0.62):
        price_cx = max(
            int(width * 0.22),
            int(food_bbox[0] - width * _PRICE_FOOD_PADDING_RATIO),
        )

    price_cy_hint = max(
        content_top_y + int(height * 0.06),
        min(fallback.price_badge_cy_hint, text_bottom_limit - int(height * 0.04)),
    )

    palette = _build_palette(
        image,
        alpha=alpha,
        food_bbox=food_bbox,
        top_text_bottom=text_bottom_limit,
    )
    scrim_height, scrim_alpha = _compute_scrim(
        image,
        alpha=alpha,
        food_bbox=food_bbox,
        top_text_bottom=text_bottom_limit,
    )

    return PosterLayoutSpec(
        width=width,
        height=height,
        food_bbox=food_bbox,
        content_top_y=content_top_y,
        text_zone_bottom=text_zone_bottom,
        max_text_width=fallback.max_text_width,
        line_gap=fallback.line_gap,
        stroke_width=fallback.stroke_width,
        price_badge_cx=price_cx,
        price_badge_cy_hint=price_cy_hint,
        store_margin_right=fallback.store_margin_right,
        store_margin_bottom=fallback.store_margin_bottom,
        palette=palette,
        scrim_height=scrim_height,
        scrim_max_alpha=scrim_alpha,
        used_fallback=False,
    )


def _build_palette(
    image: Image.Image,
    *,
    alpha: Image.Image | None,
    food_bbox: tuple[int, int, int, int] | None,
    top_text_bottom: int | None = None,
) -> PosterPaletteSpec:
    width, height = image.size
    top_bottom = top_text_bottom or int(height * 0.34)
    if food_bbox:
        top_bottom = min(top_bottom, max(int(height * 0.12), food_bbox[1] - 8))

    top_bg = _sample_background_mean_rgb(
        image,
        alpha,
        (
            int(width * 0.12),
            int(height * 0.03),
            int(width * 0.88),
            top_bottom,
        ),
    )
    bottom_right_bg = _sample_background_mean_rgb(
        image,
        alpha,
        (
            int(width * 0.52),
            int(height * 0.84),
            width,
            height,
        ),
    )

    primary = _background_hue_text_color(top_bg)
    primary_stroke = _primary_stroke_color(top_bg, primary)
    store_fill = _background_hue_text_color(bottom_right_bg)
    store_stroke = _primary_stroke_color(bottom_right_bg, store_fill)

    return _ensure_palette_readability(
        PosterPaletteSpec(
            primary_text=primary,
            primary_stroke=primary_stroke,
            store_text=store_fill,
            store_stroke=store_stroke,
            badge_outline=primary,
            badge_text=primary,
        ),
        top_bg=top_bg,
        bottom_bg=bottom_right_bg,
    )


def _ensure_palette_readability(
    palette: PosterPaletteSpec,
    *,
    top_bg: tuple[int, int, int],
    bottom_bg: tuple[int, int, int],
) -> PosterPaletteSpec:
    """밝은 배경에서 흰색/연한 글자가 나오지 않도록 보정한다."""

    primary_text = palette.primary_text
    primary_stroke = palette.primary_stroke
    top_bg_lum = _relative_luminance(top_bg)
    if top_bg_lum >= 125 and _relative_luminance(primary_text) > top_bg_lum - 48:
        primary_text = _background_hue_text_color(top_bg)
        primary_stroke = _primary_stroke_color(top_bg, primary_text)
    elif top_bg_lum >= 125 and _relative_luminance(primary_stroke) > top_bg_lum - 35:
        primary_stroke = _darker_hue_variant(primary_text, amount=0.30)

    store_text = palette.store_text
    store_stroke = palette.store_stroke
    bottom_bg_lum = _relative_luminance(bottom_bg)
    if bottom_bg_lum >= 115 and _relative_luminance(store_text) > bottom_bg_lum - 42:
        store_text = _background_hue_text_color(bottom_bg)
        store_stroke = _primary_stroke_color(bottom_bg, store_text)
    elif bottom_bg_lum >= 115 and _relative_luminance(store_stroke) > bottom_bg_lum - 35:
        store_stroke = _darker_hue_variant(store_text, amount=0.30)

    badge_outline = palette.badge_outline
    badge_text = palette.badge_text
    if top_bg_lum >= 125 and _relative_luminance(badge_text) > top_bg_lum - 48:
        badge_text = primary_text
        badge_outline = primary_text

    return PosterPaletteSpec(
        primary_text=primary_text,
        primary_stroke=primary_stroke,
        store_text=store_text,
        store_stroke=store_stroke,
        badge_outline=badge_outline,
        badge_text=badge_text,
    )


def _compute_scrim(
    image: Image.Image,
    *,
    alpha: Image.Image | None,
    food_bbox: tuple[int, int, int, int] | None,
    top_text_bottom: int,
) -> tuple[int, int]:
    width, height = image.size
    scrim_height = min(
        int(height * 0.38),
        max(int(height * 0.22), top_text_bottom + int(height * 0.02)),
    )
    if food_bbox:
        scrim_height = min(scrim_height, max(int(height * 0.18), food_bbox[1]))

    complexity = _sample_background_complexity(
        image,
        alpha,
        (int(width * 0.08), 0, int(width * 0.92), scrim_height),
    )

    if complexity < _SCRIM_COMPLEXITY_THRESHOLD:
        return scrim_height, 0

    alpha_strength = int(
        min(
            _SCRIM_MAX_ALPHA_CAP,
            (complexity - _SCRIM_COMPLEXITY_THRESHOLD) * 2.8,
        )
    )
    return scrim_height, max(24, alpha_strength)


def _sample_background_mean_rgb(
    image: Image.Image,
    alpha: Image.Image | None,
    box: tuple[int, int, int, int],
) -> tuple[int, int, int]:
    width, height = image.size
    left = max(0, min(width, box[0]))
    top = max(0, min(height, box[1]))
    right = max(left + 1, min(width, box[2]))
    bottom = max(top + 1, min(height, box[3]))

    crop_rgb = image.crop((left, top, right, bottom)).convert("RGB")
    if alpha is None:
        pixels = list(crop_rgb.getdata())
    else:
        crop_alpha = alpha.crop((left, top, right, bottom))
        pixels = [
            rgb
            for rgb, opacity in zip(crop_rgb.getdata(), crop_alpha.getdata())
            if opacity < _FOREGROUND_ALPHA_THRESHOLD
        ]
        if len(pixels) < 16:
            pixels = list(crop_rgb.getdata())

    if not pixels:
        return (120, 80, 55)

    total_r = total_g = total_b = 0
    for r, g, b in pixels:
        total_r += r
        total_g += g
        total_b += b
    count = len(pixels)
    return (total_r // count, total_g // count, total_b // count)


def _sample_background_complexity(
    image: Image.Image,
    alpha: Image.Image | None,
    box: tuple[int, int, int, int],
) -> float:
    width, height = image.size
    left = max(0, min(width, box[0]))
    top = max(0, min(height, box[1]))
    right = max(left + 1, min(width, box[2]))
    bottom = max(top + 1, min(height, box[3]))

    crop_rgb = image.crop((left, top, right, bottom)).convert("RGB")
    if alpha is None:
        pixels = list(crop_rgb.getdata())
    else:
        crop_alpha = alpha.crop((left, top, right, bottom))
        pixels = [
            rgb
            for rgb, opacity in zip(crop_rgb.getdata(), crop_alpha.getdata())
            if opacity < _FOREGROUND_ALPHA_THRESHOLD
        ]

    if len(pixels) < 16:
        return 0.0

    luminances = [_relative_luminance(pixel) for pixel in pixels]
    mean_lum = sum(luminances) / len(luminances)
    variance = sum((value - mean_lum) ** 2 for value in luminances) / len(luminances)
    return variance**0.5


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _background_hue_text_color(background_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """배경과 같은 색상 계열(Hue)을 유지한 글자색."""
    r, g, b = background_rgb
    hue, lightness, saturation = colorsys.rgb_to_hls(
        r / 255.0,
        g / 255.0,
        b / 255.0,
    )

    if saturation < 0.10:
        if lightness >= 0.55:
            factor = 0.42
            return (
                max(20, int(r * factor)),
                max(20, int(g * factor)),
                max(20, int(b * factor)),
            )
        lift = 0.72
        return (
            min(255, int(r + (255 - r) * lift)),
            min(255, int(g + (255 - g) * lift)),
            min(255, int(b + (255 - b) * lift)),
        )

    text_saturation = min(0.92, max(0.38, saturation * 1.15))
    if lightness >= 0.50:
        text_lightness = max(0.18, min(0.40, lightness * 0.58))
    else:
        text_lightness = min(0.85, max(0.55, lightness + 0.30))

    tr, tg, tb = colorsys.hls_to_rgb(hue, text_lightness, text_saturation)
    return (
        max(0, min(255, int(tr * 255))),
        max(0, min(255, int(tg * 255))),
        max(0, min(255, int(tb * 255))),
    )


def _primary_stroke_color(
    background_rgb: tuple[int, int, int],
    text_rgb: tuple[int, int, int],
) -> tuple[int, int, int]:
    bg_lum = _relative_luminance(background_rgb)
    text_lum = _relative_luminance(text_rgb)

    # 밝은 단색 배경: 흰색 halo 대신 글자색보다 진한 같은 계열 테두리
    if bg_lum >= 125:
        if text_lum < bg_lum - 20:
            return _darker_hue_variant(text_rgb, amount=0.30)
        if text_lum > bg_lum + 20:
            return _darker_hue_variant(text_rgb, amount=0.38)
        return _darker_hue_variant(text_rgb, amount=0.24)

    if text_lum < bg_lum - 25:
        return (255, 255, 255)
    if text_lum > bg_lum + 25:
        return _darker_hue_variant(text_rgb, amount=0.35)
    return (255, 255, 255) if text_lum < 128 else (30, 30, 30)


def _darker_hue_variant(
    rgb: tuple[int, int, int],
    *,
    amount: float,
) -> tuple[int, int, int]:
    r, g, b = rgb
    hue, lightness, saturation = colorsys.rgb_to_hls(
        r / 255.0,
        g / 255.0,
        b / 255.0,
    )
    stroke_lightness = max(0.08, lightness - amount)
    stroke_saturation = min(1.0, saturation * 1.05)
    sr, sg, sb = colorsys.hls_to_rgb(hue, stroke_lightness, stroke_saturation)
    return (
        max(0, min(255, int(sr * 255))),
        max(0, min(255, int(sg * 255))),
        max(0, min(255, int(sb * 255))),
    )


def _boxes_overlap(
    a: tuple[int, int, int, int],
    b: tuple[int, int, int, int],
) -> bool:
    a_left, a_top, a_right, a_bottom = a
    b_left, b_top, b_right, b_bottom = b
    return not (
        a_right <= b_left
        or a_left >= b_right
        or a_bottom <= b_top
        or a_top >= b_bottom
    )
