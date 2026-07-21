"""
포스터 PIL 템플릿 (Phase 3): 톤별 타이포 계층·가격 pill 스타일.

manifest.json tone_overrides.poster_template 을 읽는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.utils.font_registry import _get_tone_block, _load_manifest, _normalize_tone

PosterBadgeStyle = Literal["outline", "filled"]

_DEFAULT_TEMPLATE: dict[str, Any] = {
    "headline_size_ratio": 0.050,
    "subline_size_ratio": 0.034,
    "sticker_size_ratio": 0.028,
    "menu_size_ratio": 0.112,
    "price_size_ratio": 0.042,
    "store_size_ratio": 0.046,
    "headline_stroke_delta": 0,
    "headline_menu_gap_ratio": 0.014,
    "badge_style": "filled",
    "badge_pad_x_ratio": 0.034,
    "badge_pad_y_ratio": 0.016,
    "badge_outline_width_ratio": 0.0034,
    "price_cx_ratio": 0.76,
    "price_anchor": "top_right",
}

_TONE_TEMPLATE_DEFAULTS: dict[str, dict[str, Any]] = {
    "캐주얼·친근": {
        "headline_size_ratio": 0.052,
        "menu_size_ratio": 0.114,
        "badge_style": "filled",
    },
    "정중·신뢰": {
        "headline_size_ratio": 0.048,
        "menu_size_ratio": 0.102,
        "badge_style": "filled",
        "badge_outline_width_ratio": 0.0030,
    },
    "고급·감성": {
        "headline_size_ratio": 0.046,
        "menu_size_ratio": 0.106,
        "headline_menu_gap_ratio": 0.018,
        "badge_style": "filled",
        "badge_pad_x_ratio": 0.036,
    },
    "유머·이벤트": {
        "headline_size_ratio": 0.054,
        "menu_size_ratio": 0.110,
        "badge_style": "filled",
        "badge_pad_x_ratio": 0.034,
        "badge_pad_y_ratio": 0.017,
    },
}


@dataclass(frozen=True)
class PosterTemplateSpec:
    """포스터 타이포 계층·pill 스타일."""

    headline_size_ratio: float
    subline_size_ratio: float
    sticker_size_ratio: float
    menu_size_ratio: float
    price_size_ratio: float
    store_size_ratio: float
    headline_stroke_delta: int
    headline_menu_gap_ratio: float
    badge_style: PosterBadgeStyle
    badge_pad_x_ratio: float
    badge_pad_y_ratio: float
    badge_outline_width_ratio: float
    price_cx_ratio: float
    price_anchor: Literal["layout", "menu_right", "food_top_right", "top_right"]


def resolve_poster_template(tone: str | None = None) -> PosterTemplateSpec:
    """톤·manifest 기반 포스터 템플릿을 반환한다."""

    merged = dict(_DEFAULT_TEMPLATE)
    tone_key = _normalize_tone(tone)
    if tone_key and tone_key in _TONE_TEMPLATE_DEFAULTS:
        merged.update(_TONE_TEMPLATE_DEFAULTS[tone_key])

    manifest = _load_manifest()
    tone_block = _get_tone_block(manifest, tone)
    if tone_block:
        manifest_template = tone_block.get("poster_template")
        if isinstance(manifest_template, dict):
            merged.update(manifest_template)

    badge_style = str(merged.get("badge_style", "outline"))
    if badge_style not in ("outline", "filled"):
        badge_style = "outline"

    price_anchor = str(merged.get("price_anchor", "top_right"))
    if price_anchor not in ("layout", "menu_right", "food_top_right", "top_right"):
        price_anchor = "top_right"

    return PosterTemplateSpec(
        headline_size_ratio=float(merged["headline_size_ratio"]),
        subline_size_ratio=float(merged["subline_size_ratio"]),
        sticker_size_ratio=float(merged["sticker_size_ratio"]),
        menu_size_ratio=float(merged["menu_size_ratio"]),
        price_size_ratio=float(merged["price_size_ratio"]),
        store_size_ratio=float(merged["store_size_ratio"]),
        headline_stroke_delta=int(merged["headline_stroke_delta"]),
        headline_menu_gap_ratio=float(merged["headline_menu_gap_ratio"]),
        badge_style=badge_style,  # type: ignore[arg-type]
        badge_pad_x_ratio=float(merged["badge_pad_x_ratio"]),
        badge_pad_y_ratio=float(merged["badge_pad_y_ratio"]),
        badge_outline_width_ratio=float(merged["badge_outline_width_ratio"]),
        price_cx_ratio=float(merged["price_cx_ratio"]),
        price_anchor=price_anchor,  # type: ignore[arg-type]
    )


_RATIO_BOUNDS: dict[str, tuple[float, float]] = {
    "headline_size_ratio": (0.032, 0.058),
    "subline_size_ratio": (0.026, 0.042),
    "sticker_size_ratio": (0.022, 0.034),
    "menu_size_ratio": (0.082, 0.128),
    "price_size_ratio": (0.030, 0.048),
    "store_size_ratio": (0.032, 0.052),
    "headline_menu_gap_ratio": (0.008, 0.030),
    "badge_pad_x_ratio": (0.020, 0.045),
    "badge_pad_y_ratio": (0.008, 0.020),
    "badge_outline_width_ratio": (0.0020, 0.0050),
    "price_cx_ratio": (0.55, 0.88),
}


def apply_template_overrides(
    base: PosterTemplateSpec,
    overrides: dict[str, object],
) -> PosterTemplateSpec:
    """VLM JSON typography 블록을 톤 템플릿 위에 merge한다."""

    merged: dict[str, Any] = {
        "headline_size_ratio": base.headline_size_ratio,
        "subline_size_ratio": base.subline_size_ratio,
        "sticker_size_ratio": base.sticker_size_ratio,
        "menu_size_ratio": base.menu_size_ratio,
        "price_size_ratio": base.price_size_ratio,
        "store_size_ratio": base.store_size_ratio,
        "headline_stroke_delta": base.headline_stroke_delta,
        "headline_menu_gap_ratio": base.headline_menu_gap_ratio,
        "badge_style": base.badge_style,
        "badge_pad_x_ratio": base.badge_pad_x_ratio,
        "badge_pad_y_ratio": base.badge_pad_y_ratio,
        "badge_outline_width_ratio": base.badge_outline_width_ratio,
        "price_cx_ratio": base.price_cx_ratio,
        "price_anchor": base.price_anchor,
    }
    merged.update(overrides)

    for key, (low, high) in _RATIO_BOUNDS.items():
        if key in merged:
            merged[key] = max(low, min(high, float(merged[key])))

    if merged["headline_size_ratio"] >= merged["menu_size_ratio"]:
        merged["headline_size_ratio"] = max(
            _RATIO_BOUNDS["headline_size_ratio"][0],
            merged["menu_size_ratio"] - 0.040,
        )

    badge_style = str(merged.get("badge_style", "outline"))
    if badge_style not in ("outline", "filled"):
        badge_style = "outline"

    price_anchor = str(merged.get("price_anchor", "top_right"))
    if price_anchor not in ("layout", "menu_right", "food_top_right", "top_right"):
        price_anchor = "top_right"

    return PosterTemplateSpec(
        headline_size_ratio=float(merged["headline_size_ratio"]),
        subline_size_ratio=float(merged["subline_size_ratio"]),
        sticker_size_ratio=float(merged["sticker_size_ratio"]),
        menu_size_ratio=float(merged["menu_size_ratio"]),
        price_size_ratio=float(merged["price_size_ratio"]),
        store_size_ratio=float(merged["store_size_ratio"]),
        headline_stroke_delta=int(merged["headline_stroke_delta"]),
        headline_menu_gap_ratio=float(merged["headline_menu_gap_ratio"]),
        badge_style=badge_style,  # type: ignore[arg-type]
        badge_pad_x_ratio=float(merged["badge_pad_x_ratio"]),
        badge_pad_y_ratio=float(merged["badge_pad_y_ratio"]),
        badge_outline_width_ratio=float(merged["badge_outline_width_ratio"]),
        price_cx_ratio=float(merged["price_cx_ratio"]),
        price_anchor=price_anchor,  # type: ignore[arg-type]
    )


def resolve_poster_template_for_layout(
    tone: str | None,
    *,
    vlm_template: PosterTemplateSpec | None = None,
) -> PosterTemplateSpec:
    """톤 기본 템플릿 위에 VLM typography를 merge한다."""

    base = resolve_poster_template(tone)
    if vlm_template is None:
        return base
    return apply_template_overrides(
        base,
        {
            "headline_size_ratio": vlm_template.headline_size_ratio,
            "subline_size_ratio": vlm_template.subline_size_ratio,
            "sticker_size_ratio": vlm_template.sticker_size_ratio,
            "menu_size_ratio": vlm_template.menu_size_ratio,
            "price_size_ratio": vlm_template.price_size_ratio,
            "store_size_ratio": vlm_template.store_size_ratio,
            "headline_stroke_delta": vlm_template.headline_stroke_delta,
            "headline_menu_gap_ratio": vlm_template.headline_menu_gap_ratio,
            "badge_pad_x_ratio": vlm_template.badge_pad_x_ratio,
            "badge_pad_y_ratio": vlm_template.badge_pad_y_ratio,
            "badge_outline_width_ratio": vlm_template.badge_outline_width_ratio,
        },
    )
