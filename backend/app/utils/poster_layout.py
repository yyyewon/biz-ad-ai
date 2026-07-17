"""
포스터 PIL 합성용 레이아웃 분석.

rembg로 음식 전경 mask/bbox를 추정하고, 텍스트·pill·가게명 배치에 쓸
LayoutSpec을 만든다. 분석 실패 시 고정 비율 fallback을 쓴다.
"""

from __future__ import annotations

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


@dataclass(frozen=True)
class PosterLayoutSpec:
    """포스터 텍스트 합성에 필요한 배치 파라미터."""

    width: int
    height: int
    food_bbox: tuple[int, int, int, int] | None
    content_top_y: int
    max_text_width: int
    line_gap: int
    stroke_width: int
    price_badge_cx: int
    price_badge_cy_hint: int
    store_margin_right: int
    store_margin_bottom: int
    used_fallback: bool

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

        # 음식 왼쪽 빈 공간에 pill 배치 시도
        candidate_cx = max(half_w, left - pad - half_w)
        candidate_box = (
            candidate_cx - half_w,
            cy - half_h,
            candidate_cx + half_w,
            cy + half_h,
        )
        if not _boxes_overlap(candidate_box, food_box):
            return candidate_cx, cy

        # 상단으로 올림
        candidate_cy = max(self.content_top_y + half_h, top - pad - half_h)
        return cx, candidate_cy

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
    포스터 이미지에서 음식 bbox를 추정하고 텍스트 배치 spec을 반환한다.

    layout_mode는 현재 single만 지원한다. multi는 Phase 5에서 확장한다.
    """

    if layout_mode != "single":
        logger.warning(
            "poster_layout_unsupported_mode | mode={} | fallback=single",
            layout_mode,
        )

    width, height = image.size
    fallback = _build_fallback_spec(width, height)

    try:
        food_bbox = _detect_food_bbox(image)
    except Exception as exc:
        logger.warning(
            "poster_layout_rembg_failed | error={} | using_fallback=true",
            str(exc),
        )
        return fallback

    if food_bbox is None:
        logger.info("poster_layout_no_food_bbox | using_fallback=true")
        return fallback

    if not _is_valid_food_bbox(food_bbox, width, height):
        logger.info(
            "poster_layout_invalid_food_bbox | bbox={} | using_fallback=true",
            food_bbox,
        )
        return fallback

    return _build_spec_from_food_bbox(width, height, food_bbox)


def _get_rembg_session():
    global _rembg_session

    with _rembg_lock:
        if _rembg_session is None:
            from rembg import new_session

            _rembg_session = new_session("u2net")
        return _rembg_session


def _detect_food_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    from rembg import remove

    rgb_image = image.convert("RGB")
    buffer = io.BytesIO()
    rgb_image.save(buffer, format="PNG")
    input_bytes = buffer.getvalue()

    session = _get_rembg_session()
    output_bytes = remove(input_bytes, session=session)
    rgba = Image.open(io.BytesIO(output_bytes)).convert("RGBA")
    alpha = rgba.split()[-1]
    return alpha.getbbox()


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


def _build_fallback_spec(width: int, height: int) -> PosterLayoutSpec:
    return PosterLayoutSpec(
        width=width,
        height=height,
        food_bbox=None,
        content_top_y=int(height * _FALLBACK_CONTENT_TOP_RATIO),
        max_text_width=int(width * _FALLBACK_MAX_TEXT_WIDTH_RATIO),
        line_gap=max(6, int(height * _FALLBACK_LINE_GAP_RATIO)),
        stroke_width=max(1, int(width * _FALLBACK_STROKE_WIDTH_RATIO)),
        price_badge_cx=int(width * _FALLBACK_PRICE_CX_RATIO),
        price_badge_cy_hint=int(height * _FALLBACK_PRICE_CY_RATIO),
        store_margin_right=int(width * _FALLBACK_STORE_MARGIN_RIGHT_RATIO),
        store_margin_bottom=int(height * _FALLBACK_STORE_MARGIN_BOTTOM_RATIO),
        used_fallback=True,
    )


def _build_spec_from_food_bbox(
    width: int,
    height: int,
    food_bbox: tuple[int, int, int, int],
) -> PosterLayoutSpec:
    fallback = _build_fallback_spec(width, height)
    _, food_top, food_right, _ = food_bbox

    content_top_y = fallback.content_top_y
    text_bottom_limit = max(
        content_top_y + int(height * 0.08),
        food_top - max(8, int(height * _FOOD_TOP_PADDING_RATIO)),
    )

    # 음식 상단이 너무 높으면 fallback
    if text_bottom_limit <= content_top_y + int(height * 0.05):
        return fallback

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

    return PosterLayoutSpec(
        width=width,
        height=height,
        food_bbox=food_bbox,
        content_top_y=content_top_y,
        max_text_width=fallback.max_text_width,
        line_gap=fallback.line_gap,
        stroke_width=fallback.stroke_width,
        price_badge_cx=price_cx,
        price_badge_cy_hint=price_cy_hint,
        store_margin_right=fallback.store_margin_right,
        store_margin_bottom=fallback.store_margin_bottom,
        used_fallback=False,
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
