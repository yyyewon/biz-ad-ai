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
_PRICE_SHOULDER_TOP_RATIO = 0.02
_PRICE_SHOULDER_OVERLAP_RATIO = 0.42
_PRICE_RIM_Y_RATIO = 0.30
_MENU_FOOD_GAP_RATIO = 0.014
_COPY_MENU_GAP_RATIO = 0.012
_COPY_COLUMN_MAX_WIDTH_RATIO = 0.56
_FOOD_BBOX_MIN_TOP_SHRINK_RATIO = 0.10
_FOOD_BBOX_SIDE_TRIM_RATIO = 0.03
_FOOD_INTRUSION_TOP_RATIO = 0.38
_FOOD_COLLISION_PAD_RATIO = 0.012

_FOREGROUND_ALPHA_THRESHOLD = 128
_SCRIM_COMPLEXITY_THRESHOLD = 22.0
_SCRIM_MAX_ALPHA_CAP = 150
_MIN_ANALYSIS_SIDE_PX = 64


@dataclass(frozen=True)
class PosterPaletteSpec:
    """포스터 텍스트·pill 색상 (역할별 분리)."""

    primary_text: tuple[int, int, int]
    primary_stroke: tuple[int, int, int]
    accent_text: tuple[int, int, int]
    store_text: tuple[int, int, int]
    store_stroke: tuple[int, int, int]
    badge_fill: tuple[int, int, int]
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
    food_visual_top: int | None = None
    vlm_template_overrides: dict[str, object] | None = None
    foreground_alpha: Image.Image | None = None

    def _menu_anchor_top(self) -> int | None:
        """메뉴·카피 스택 기준 음식 상단 (rembg raw top, refine 전)."""

        if self.food_visual_top is not None:
            return self.food_visual_top
        if self.food_bbox:
            return self.food_bbox[1]
        return None

    def _menu_food_gap(self, menu_block_height: int) -> int:
        base = max(12, int(self.height * _MENU_FOOD_GAP_RATIO))
        font_pad = max(8, int(menu_block_height * 0.14))
        return max(base, font_pad)

    def resolve_text_block_start_y(self, block_height: int) -> int:
        """음식 위 상단 존 안에서 문구+메뉴명 블록 시작 Y를 계산한다."""

        margin_top = max(self.content_top_y, int(self.height * _TEXT_ZONE_TOP_RATIO))
        zone_bottom = self.text_zone_bottom
        anchor_top = self._menu_anchor_top()
        if zone_bottom is None and anchor_top is not None:
            zone_bottom = anchor_top - max(8, int(self.height * _FOOD_TOP_PADDING_RATIO))
        if zone_bottom is None:
            zone_bottom = int(self.height * 0.34)

        zone_bottom = min(zone_bottom, self.height)
        zone_height = max(0, zone_bottom - margin_top)
        min_block = max(1, block_height)
        if zone_height <= min_block:
            return margin_top

        slack = zone_height - min_block
        offset = int(slack * (1.0 - _TEXT_ZONE_BIAS_TOWARD_FOOD))
        start_y = margin_top + offset
        end_y = start_y + min_block
        if end_y > zone_bottom:
            start_y = max(margin_top, zone_bottom - min_block)
        return start_y

    def resolve_text_stack_y(
        self,
        *,
        menu_block_height: int,
        copy_block_height: int,
    ) -> tuple[int, int]:
        """카피는 상단 고정, 메뉴명은 음식 visual top 기준 (서로 독립)."""

        margin_top = max(self.content_top_y, int(self.height * _TEXT_ZONE_TOP_RATIO))
        menu_h = max(1, menu_block_height)
        copy_h = max(1, copy_block_height)
        pad = self._menu_food_gap(menu_h)

        copy_y = margin_top

        anchor_top = self._menu_anchor_top()
        if anchor_top is not None:
            menu_y = max(self.content_top_y, anchor_top - pad - menu_h)
        else:
            gap = max(8, int(self.height * _COPY_MENU_GAP_RATIO))
            menu_y = margin_top + copy_h + gap

        return copy_y, menu_y

    def resolve_menu_block_start_y(
        self,
        menu_block_height: int,
        *,
        copy_block_height: int = 0,
    ) -> int:
        """메뉴명 블록 Y (resolve_text_stack_y 래퍼)."""

        _, menu_y = self.resolve_text_stack_y(
            menu_block_height=menu_block_height,
            copy_block_height=copy_block_height,
        )
        return menu_y

    def resolve_copy_block_start_y(self, copy_block_height: int, *, menu_start_y: int) -> int:
        """스티커·문구·서브카피 시작 Y (menu_start_y 기준 역산)."""

        gap = max(8, int(self.height * _COPY_MENU_GAP_RATIO))
        margin_top = max(self.content_top_y, int(self.height * _TEXT_ZONE_TOP_RATIO))
        block = max(1, copy_block_height)
        return max(margin_top, menu_start_y - gap - block)

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

    def _food_collision_pad(self) -> int:
        return max(8, int(self.height * _FOOD_COLLISION_PAD_RATIO))

    def _padded_food_box(self) -> tuple[int, int, int, int] | None:
        if not self.food_bbox:
            return None
        left, top, right, bottom = self.food_bbox
        pad = self._food_collision_pad()
        return (left - pad, top - pad, right + pad, bottom + pad)

    def food_intrudes_text_zone(self) -> bool:
        """음식 상단이 프롬프트 상단 텍스트 존(약 38%) 안으로 올라왔는지."""

        anchor = self._menu_anchor_top()
        if anchor is None:
            return False
        return anchor < int(self.height * _FOOD_INTRUSION_TOP_RATIO)

    def text_block_overlaps_food(
        self,
        *,
        top_y: int,
        block_height: int,
        text_width: int,
        left_x: int | None = None,
    ) -> bool:
        food_box = self._padded_food_box()
        if food_box is None:
            return False

        block_h = max(1, block_height)
        if left_x is not None:
            text_box = (
                max(0, left_x),
                top_y,
                min(self.width, left_x + max(1, text_width)),
                top_y + block_h,
            )
        else:
            half_w = max(1, text_width) // 2
            center_x = self.width // 2
            text_box = (
                max(0, center_x - half_w),
                top_y,
                min(self.width, center_x + half_w),
                top_y + block_h,
            )
        return _boxes_overlap(text_box, food_box)

    def badge_overlaps_food(
        self,
        *,
        center_x: int,
        center_y: int,
        badge_width: int,
        badge_height: int,
    ) -> bool:
        food_box = self._padded_food_box()
        if food_box is None:
            return False

        half_w = badge_width // 2
        half_h = badge_height // 2
        badge_box = (
            center_x - half_w,
            center_y - half_h,
            center_x + half_w,
            center_y + half_h,
        )
        return _boxes_overlap(badge_box, food_box)

    def clamp_menu_block_y(
        self,
        menu_y: int,
        menu_block_height: int,
        *,
        text_width: int,
        left_x: int | None = None,
        min_y: int | None = None,
        allow_lift: bool = True,
    ) -> tuple[int, bool]:
        """
        메뉴명 블록이 음식 bbox와 겹치지 않도록 Y를 조정한다.

        min_y: 카피 블록 아래 등 메뉴가 올라갈 수 없는 하한. allow_lift=False면 축소만 허용.
        """

        margin_top = max(self.content_top_y, int(self.height * _TEXT_ZONE_TOP_RATIO))
        floor_y = max(margin_top, min_y) if min_y is not None else margin_top
        menu_h = max(1, menu_block_height)
        menu_y = max(floor_y, menu_y)

        if not self.text_block_overlaps_food(
            top_y=menu_y,
            block_height=menu_h,
            text_width=text_width,
            left_x=left_x,
        ):
            return menu_y, False

        if not allow_lift:
            return menu_y, True

        food_box = self._padded_food_box()
        if food_box is None:
            return menu_y, False

        _, food_top, _, _ = food_box
        lifted_y = max(floor_y, food_top - menu_h)
        if not self.text_block_overlaps_food(
            top_y=lifted_y,
            block_height=menu_h,
            text_width=text_width,
            left_x=left_x,
        ):
            return lifted_y, False

        if min_y is not None:
            return floor_y, True

        fixed_y = max(floor_y, int(self.height * 0.20))
        fixed_y = min(fixed_y, lifted_y)
        return fixed_y, True

    def clamp_text_block_top_left(
        self,
        *,
        x: int,
        y: int,
        block_width: int,
        block_height: int,
    ) -> tuple[int, int]:
        """카피·스티커 블록이 화면·음식과 겹치지 않도록 좌상단을 조정한다."""

        margin_top = max(self.content_top_y, int(self.height * _TEXT_ZONE_TOP_RATIO))
        block_w = max(1, block_width)
        block_h = max(1, block_height)
        margin_x = max(8, int(self.width * 0.04))

        clamped_x = max(margin_x, min(self.width - block_w - margin_x, x))
        clamped_y = max(margin_top, y)

        if not self.text_block_overlaps_food(
            top_y=clamped_y,
            block_height=block_h,
            text_width=block_w,
            left_x=clamped_x,
        ):
            return clamped_x, clamped_y

        food_box = self._padded_food_box()
        if food_box is None:
            return clamped_x, clamped_y

        _, food_top, _, _ = food_box
        lifted_y = max(margin_top, food_top - block_h - self._food_collision_pad())
        if not self.text_block_overlaps_food(
            top_y=lifted_y,
            block_height=block_h,
            text_width=block_w,
            left_x=clamped_x,
        ):
            return clamped_x, lifted_y

        return clamped_x, clamped_y

    def should_use_food_shoulder_price(self) -> bool:
        """음식 bbox가 있으면 가격 pill을 음식 우상단 어깨에 붙인다."""

        return self.food_bbox is not None

    def resolve_price_badge_food_top_right(
        self,
        *,
        badge_width: int,
        badge_height: int,
        menu_block_bottom: int | None = None,
        respect_menu_block: bool = True,
    ) -> tuple[int, int]:
        """가격 pill을 음식 우측 상단 rim에 살짝 겹쳐 붙인다."""

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

        left, top, right, bottom = self.food_bbox
        food_height = max(1, bottom - top)
        food_width = max(1, right - left)
        menu_gap = max(10, int(self.height * 0.012))

        inset_x = max(2, int(food_width * 0.03))
        badge_right = min(self.width - margin, right - inset_x)
        badge_left = int(badge_right - badge_width * (1.0 - _PRICE_SHOULDER_OVERLAP_RATIO))
        badge_left = max(margin, min(self.width - badge_width - margin, badge_left))
        badge_cx = int(badge_left + badge_width / 2)

        rim_y = top + int(food_height * _PRICE_RIM_Y_RATIO)
        badge_cy = int(rim_y - badge_height * 0.12)

        if respect_menu_block and menu_block_bottom is not None:
            min_cy = menu_block_bottom + menu_gap + half_h
            if badge_cy < min_cy:
                badge_cy = min_cy

        badge_cx = max(half_w + margin, min(self.width - half_w - margin, badge_cx))
        badge_cy = max(half_h + margin, min(self.height - half_h - margin, badge_cy))
        return badge_cx, badge_cy

    def resolve_price_badge_safe_zone(
        self,
        *,
        badge_width: int,
        badge_height: int,
        menu_block_bottom: int | None = None,
    ) -> tuple[int, int]:
        """음식이 높을 때 가격 pill을 상단 우측 안전 구역에 둔다."""

        margin = max(12, int(self.width * 0.04))
        half_w = badge_width // 2
        half_h = badge_height // 2
        gap = max(10, int(self.height * 0.012))

        if menu_block_bottom is not None:
            badge_cy = menu_block_bottom + gap + half_h
        else:
            badge_cy = self.price_badge_cy_hint

        badge_cx = self.width - margin - half_w
        return self.clamp_price_badge_center(
            center_x=badge_cx,
            center_y=badge_cy,
            badge_width=badge_width,
            badge_height=badge_height,
        )

    def resolve_price_badge_top_right(
        self,
        *,
        badge_width: int,
        badge_height: int,
    ) -> tuple[int, int]:
        """가격 pill을 포스터 우상단에 고정한다."""

        margin = max(12, int(self.width * 0.04))
        half_w = badge_width // 2
        half_h = badge_height // 2
        badge_cx = self.width - margin - half_w
        top_y = max(self.content_top_y, int(self.height * 0.06))
        badge_cy = top_y + half_h
        return self.clamp_price_badge_center(
            center_x=badge_cx,
            center_y=badge_cy,
            badge_width=badge_width,
            badge_height=badge_height,
        )

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

    if min(width, height) < _MIN_ANALYSIS_SIDE_PX:
        logger.info(
            "poster_layout_tiny_image | size={}x{} | using_fallback=true",
            width,
            height,
        )
        return _build_fallback_spec(rgb_image, food_bbox=None, alpha=None)

    alpha: Image.Image | None = None
    food_bbox: tuple[int, int, int, int] | None = None
    food_visual_top: int | None = None

    try:
        alpha = _detect_foreground_alpha(rgb_image)
        raw_bbox = alpha.getbbox()
        food_visual_top = raw_bbox[1] if raw_bbox else None
        food_bbox = _refine_food_bbox(alpha, raw_bbox, width, height) if raw_bbox else None
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

    spec = _build_spec_from_food_bbox(
        rgb_image,
        food_bbox,
        alpha=alpha,
        food_visual_top=food_visual_top,
    )
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
        food_visual_top=spec.food_visual_top,
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
        vlm_template_overrides=hints.template_overrides,
        foreground_alpha=spec.foreground_alpha,
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

    accent_text = vlm_palette.accent_text
    if _accent_should_use_rules(accent_text, top_bg):
        accent_text = rules_palette.accent_text
        used_rules = True

    store_text = vlm_palette.store_text
    store_stroke = vlm_palette.store_stroke
    if not _text_bg_contrast_ok(store_text, bottom_bg):
        store_text = rules_palette.store_text
        store_stroke = rules_palette.store_stroke
        used_rules = True
    elif not _text_bg_contrast_ok(store_stroke, bottom_bg):
        store_stroke = _primary_stroke_color(bottom_bg, store_text)

    badge_fill = vlm_palette.badge_fill
    badge_text = vlm_palette.badge_text
    badge_outline = vlm_palette.badge_outline
    if not _text_bg_contrast_ok(badge_text, badge_fill):
        badge_text = rules_palette.badge_text
        used_rules = True
    if not _text_bg_contrast_ok(badge_outline, badge_fill):
        badge_outline = rules_palette.badge_outline
        used_rules = True

    return (
        _ensure_palette_readability(
            PosterPaletteSpec(
                primary_text=primary_text,
                primary_stroke=primary_stroke,
                accent_text=accent_text,
                store_text=store_text,
                store_stroke=store_stroke,
                badge_fill=badge_fill,
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
        palette.accent_text,
        palette.store_text,
        palette.store_stroke,
        palette.badge_fill,
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


def warm_up_poster_layout() -> None:
    """
    첫 광고 요청 전에 rembg 모델과 ONNX 세션을 준비
    """

    _get_rembg_session()


def _detect_foreground_alpha(image: Image.Image) -> Image.Image:
    from rembg import remove

    rgb_image = image.convert("RGB")
    buffer = io.BytesIO()
    rgb_image.save(buffer, format="PNG")

    session = _get_rembg_session()
    output_bytes = remove(buffer.getvalue(), session=session)
    rgba = Image.open(io.BytesIO(output_bytes)).convert("RGBA")
    return rgba.split()[-1]


def _refine_food_bbox(
    alpha: Image.Image,
    raw_bbox: tuple[int, int, int, int],
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    """빨대·가장자리 노이즈를 줄이기 위해 foreground 밀도 기준으로 bbox를 조정."""

    left, top, right, bottom = raw_bbox
    box_w = right - left
    box_h = bottom - top
    if box_w < 16 or box_h < 16:
        return raw_bbox

    x_margin = int(box_w * 0.18)
    scan_left = left + x_margin
    scan_right = right - x_margin
    if scan_right <= scan_left:
        scan_left, scan_right = left, right

    row_counts: list[tuple[int, int]] = []
    x_step = max(1, (scan_right - scan_left) // 64)
    for y in range(top, bottom):
        count = sum(
            1
            for x in range(scan_left, scan_right, x_step)
            if alpha.getpixel((x, y)) >= _FOREGROUND_ALPHA_THRESHOLD
        )
        row_counts.append((y, count))

    max_count = max((count for _, count in row_counts), default=0)
    if max_count <= 0:
        return raw_bbox

    threshold = max(3, int(max_count * 0.35))
    dense_rows = [y for y, count in row_counts if count >= threshold]
    if not dense_rows:
        return raw_bbox

    body_top = max(top, min(dense_rows))
    body_top = max(body_top, top + int(box_h * _FOOD_BBOX_MIN_TOP_SHRINK_RATIO))

    xs: list[int] = []
    y_step = max(1, (bottom - body_top) // 40)
    x_step = max(1, box_w // 80)
    for y in range(body_top, bottom, y_step):
        for x in range(left, right, x_step):
            if alpha.getpixel((x, y)) >= _FOREGROUND_ALPHA_THRESHOLD:
                xs.append(x)

    if len(xs) < 20:
        new_left = left + int(box_w * _FOOD_BBOX_SIDE_TRIM_RATIO)
        new_right = right - int(box_w * _FOOD_BBOX_SIDE_TRIM_RATIO)
    else:
        xs.sort()
        n = len(xs)
        new_left = xs[int(n * _FOOD_BBOX_SIDE_TRIM_RATIO)]
        new_right = xs[int(n * (1.0 - _FOOD_BBOX_SIDE_TRIM_RATIO))]

    new_bottom = max(body_top + 8, bottom - int(box_h * 0.01))
    refined = (
        max(0, new_left),
        max(0, body_top),
        min(width, new_right),
        min(height, new_bottom),
    )

    if not _is_valid_food_bbox(refined, width, height):
        return raw_bbox
    return refined


def _accent_should_use_rules(
    accent_rgb: tuple[int, int, int],
    top_bg: tuple[int, int, int],
) -> bool:
    """메뉴명 accent가 너무 밝거나 배경과 구분이 약하면 rules palette를 쓴다."""

    if not _text_bg_contrast_ok(accent_rgb, top_bg):
        return True

    top_lum = _relative_luminance(top_bg)
    accent_lum = _relative_luminance(accent_rgb)
    if accent_lum >= 235:
        return True
    if top_lum >= 125 and accent_lum >= top_lum - 50:
        return True
    if top_lum >= 125 and accent_lum >= 175:
        return True
    return False


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
    food_visual_top: int | None = None,
) -> PosterLayoutSpec:
    width, height = image.size
    palette = _build_palette(image, alpha=alpha, food_bbox=food_bbox)
    scrim_height, scrim_alpha = _compute_scrim(
        image,
        alpha=alpha,
        food_bbox=food_bbox,
        top_text_bottom=int(height * 0.34),
    )

    anchor_top = food_visual_top if food_visual_top is not None else (
        food_bbox[1] if food_bbox else None
    )

    return PosterLayoutSpec(
        width=width,
        height=height,
        food_bbox=food_bbox,
        food_visual_top=food_visual_top,
        content_top_y=int(height * _FALLBACK_CONTENT_TOP_RATIO),
        text_zone_bottom=int(height * 0.34) if anchor_top is None else (
            anchor_top - max(8, int(height * _FOOD_TOP_PADDING_RATIO))
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
        foreground_alpha=alpha,
    )


def _build_spec_from_food_bbox(
    image: Image.Image,
    food_bbox: tuple[int, int, int, int],
    *,
    alpha: Image.Image | None,
    food_visual_top: int | None = None,
) -> PosterLayoutSpec:
    width, height = image.size
    fallback = _build_fallback_spec(
        image,
        food_bbox=food_bbox,
        alpha=alpha,
        food_visual_top=food_visual_top,
    )
    _, food_top, food_right, _ = food_bbox
    anchor_top = food_visual_top if food_visual_top is not None else food_top

    content_top_y = fallback.content_top_y
    text_bottom_limit = max(
        content_top_y + int(height * 0.08),
        anchor_top - max(8, int(height * _FOOD_TOP_PADDING_RATIO)),
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
        food_visual_top=food_visual_top,
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
        foreground_alpha=alpha,
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

    food_rgb = _sample_food_mean_rgb(image, alpha, food_bbox)
    primary = _background_hue_text_color(top_bg)
    primary_stroke = _primary_stroke_color(top_bg, primary)
    accent = _build_accent_text(food_rgb, top_bg, primary)
    store_fill = _build_muted_store_text(accent, bottom_right_bg)
    store_stroke = _primary_stroke_color(bottom_right_bg, store_fill)
    badge_fill = _build_badge_fill_color(top_bg)
    badge_text = _contrast_text_on_badge_fill(badge_fill, accent)
    badge_outline = _darker_hue_variant(accent, amount=0.14)

    return _ensure_palette_readability(
        PosterPaletteSpec(
            primary_text=primary,
            primary_stroke=primary_stroke,
            accent_text=accent,
            store_text=store_fill,
            store_stroke=store_stroke,
            badge_fill=badge_fill,
            badge_outline=badge_outline,
            badge_text=badge_text,
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

    accent_text = palette.accent_text
    if _accent_should_use_rules(accent_text, top_bg):
        accent_text = _build_accent_text(None, top_bg, primary_text)
    elif not _text_bg_contrast_ok(accent_text, top_bg):
        accent_text = _build_accent_text(None, top_bg, primary_text)

    store_text = palette.store_text
    store_stroke = palette.store_stroke
    bottom_bg_lum = _relative_luminance(bottom_bg)
    if not _text_bg_contrast_ok(store_text, bottom_bg):
        store_text = _build_muted_store_text(accent_text, bottom_bg)
        store_stroke = _primary_stroke_color(bottom_bg, store_text)
    elif bottom_bg_lum >= 115 and _relative_luminance(store_stroke) > bottom_bg_lum - 35:
        store_stroke = _darker_hue_variant(store_text, amount=0.30)

    badge_fill = palette.badge_fill
    badge_text = palette.badge_text
    badge_outline = palette.badge_outline
    if _relative_luminance(badge_fill) < 40 or _relative_luminance(badge_fill) > 245:
        badge_fill = _build_badge_fill_color(top_bg)
    if not _text_bg_contrast_ok(badge_text, badge_fill):
        badge_text = _contrast_text_on_badge_fill(badge_fill, accent_text)
    if not _text_bg_contrast_ok(badge_outline, badge_fill):
        badge_outline = _darker_hue_variant(accent_text, amount=0.14)

    return PosterPaletteSpec(
        primary_text=primary_text,
        primary_stroke=primary_stroke,
        accent_text=accent_text,
        store_text=store_text,
        store_stroke=store_stroke,
        badge_fill=badge_fill,
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
        pixels = list(crop_rgb.get_flattened_data())
    else:
        crop_alpha = alpha.crop((left, top, right, bottom))
        pixels = [
            rgb
            for rgb, opacity in zip(
                crop_rgb.get_flattened_data(),
                crop_alpha.get_flattened_data(),
            )
            if opacity < _FOREGROUND_ALPHA_THRESHOLD
        ]
        if len(pixels) < 16:
            pixels = list(crop_rgb.get_flattened_data())

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
        pixels = list(crop_rgb.get_flattened_data())
    else:
        crop_alpha = alpha.crop((left, top, right, bottom))
        pixels = [
            rgb
            for rgb, opacity in zip(
                crop_rgb.get_flattened_data(),
                crop_alpha.get_flattened_data(),
            )
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


def _sample_food_mean_rgb(
    image: Image.Image,
    alpha: Image.Image | None,
    food_bbox: tuple[int, int, int, int] | None,
) -> tuple[int, int, int] | None:
    if food_bbox is None or alpha is None:
        return None

    width, height = image.size
    left, top, right, bottom = food_bbox
    left = max(0, min(width - 1, left))
    top = max(0, min(height - 1, top))
    right = max(left + 1, min(width, right))
    bottom = max(top + 1, min(height, bottom))

    crop_rgb = image.crop((left, top, right, bottom)).convert("RGB")
    crop_alpha = alpha.crop((left, top, right, bottom))
    pixels = [
        rgb
        for rgb, opacity in zip(
            crop_rgb.get_flattened_data(),
            crop_alpha.get_flattened_data(),
        )
        if opacity >= _FOREGROUND_ALPHA_THRESHOLD
    ]
    if len(pixels) < 24:
        return None

    total_r = total_g = total_b = 0
    for r, g, b in pixels:
        total_r += r
        total_g += g
        total_b += b
    count = len(pixels)
    return (total_r // count, total_g // count, total_b // count)


def _build_accent_text(
    food_rgb: tuple[int, int, int] | None,
    background_rgb: tuple[int, int, int],
    primary_text: tuple[int, int, int],
) -> tuple[int, int, int]:
    """메뉴명 accent: 음식색 기반, 없으면 배경 보색."""

    bg_lum = _relative_luminance(background_rgb)
    if food_rgb is not None:
        r, g, b = food_rgb
        hue, lightness, saturation = colorsys.rgb_to_hls(
            r / 255.0,
            g / 255.0,
            b / 255.0,
        )
        if bg_lum >= 125:
            text_lightness = max(0.14, min(0.34, lightness * 0.52))
            text_saturation = min(0.95, max(0.42, saturation * 1.22))
        else:
            text_lightness = min(0.88, max(0.58, lightness + 0.22))
            text_saturation = min(0.92, max(0.35, saturation * 1.05))
        tr, tg, tb = colorsys.hls_to_rgb(hue, text_lightness, text_saturation)
        accent = (
            max(0, min(255, int(tr * 255))),
            max(0, min(255, int(tg * 255))),
            max(0, min(255, int(tb * 255))),
        )
        if _text_bg_contrast_ok(accent, background_rgb):
            return accent

    r, g, b = background_rgb
    hue, lightness, saturation = colorsys.rgb_to_hls(
        r / 255.0,
        g / 255.0,
        b / 255.0,
    )
    comp_hue = (hue + 0.5) % 1.0
    if bg_lum >= 125:
        text_lightness = 0.30
        text_saturation = min(0.88, max(0.42, saturation * 1.1))
    else:
        text_lightness = 0.78
        text_saturation = min(0.85, max(0.35, saturation))
    tr, tg, tb = colorsys.hls_to_rgb(comp_hue, text_lightness, text_saturation)
    accent = (
        max(0, min(255, int(tr * 255))),
        max(0, min(255, int(tg * 255))),
        max(0, min(255, int(tb * 255))),
    )
    if _text_bg_contrast_ok(accent, background_rgb):
        return accent
    return _darker_hue_variant(primary_text, amount=0.08)


def _build_muted_store_text(
    accent_rgb: tuple[int, int, int],
    background_rgb: tuple[int, int, int],
) -> tuple[int, int, int]:
    """가게명: accent보다 연하고 채도 낮게."""

    r, g, b = accent_rgb
    hue, lightness, saturation = colorsys.rgb_to_hls(
        r / 255.0,
        g / 255.0,
        b / 255.0,
    )
    bg_lum = _relative_luminance(background_rgb)
    if bg_lum >= 125:
        store_lightness = min(0.46, max(0.30, lightness + 0.12))
        store_saturation = max(0.18, saturation * 0.55)
    else:
        store_lightness = min(0.82, max(0.58, lightness + 0.18))
        store_saturation = max(0.15, saturation * 0.50)
    sr, sg, sb = colorsys.hls_to_rgb(hue, store_lightness, store_saturation)
    store = (
        max(0, min(255, int(sr * 255))),
        max(0, min(255, int(sg * 255))),
        max(0, min(255, int(sb * 255))),
    )
    if _text_bg_contrast_ok(store, background_rgb):
        return store
    return _background_hue_text_color(background_rgb)


def _build_badge_fill_color(background_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """가격 pill 배경: 크림/오프화이트 + 배경 hue 살짝 반영."""

    r, g, b = background_rgb
    hue, _, _ = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    tr, tg, tb = colorsys.hls_to_rgb(hue, 0.965, 0.06)
    tinted = (
        max(0, min(255, int(tr * 255))),
        max(0, min(255, int(tg * 255))),
        max(0, min(255, int(tb * 255))),
    )
    cream = (248, 245, 238)
    return (
        (tinted[0] + cream[0]) // 2,
        (tinted[1] + cream[1]) // 2,
        (tinted[2] + cream[2]) // 2,
    )


def _contrast_text_on_badge_fill(
    fill_rgb: tuple[int, int, int],
    preferred_text: tuple[int, int, int],
) -> tuple[int, int, int]:
    if _text_bg_contrast_ok(preferred_text, fill_rgb):
        return preferred_text
    if _relative_luminance(fill_rgb) < 150:
        return (255, 255, 255)
    return _darker_hue_variant(preferred_text, amount=0.32)

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
