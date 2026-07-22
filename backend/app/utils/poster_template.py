"""
포스터 PIL 템플릿: 톤별 타이포 계층과 의미 기반 디자인 토큰
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from app.utils.font_registry import _get_tone_block, _load_manifest, _normalize_tone

PosterBadgeStyle = Literal["outline", "filled"]
PosterComposition = Literal["editorial", "centered", "framed"]
PosterPriceStyle = Literal["label", "ticket", "stamp"]

_TEMPLATE_ID_OVERRIDES: dict[str, dict[str, object]] = {
    "editorial": {"composition": "editorial", "price_style": "label"},
    "centered": {"composition": "centered", "price_style": "ticket"},
    "framed": {"composition": "framed", "price_style": "ticket"},
}

_DENSITY_OVERRIDES: dict[str, dict[str, object]] = {
    "compact": {"headline_menu_gap_ratio": 0.010},
    "balanced": {"headline_menu_gap_ratio": 0.016},
    "airy": {"headline_menu_gap_ratio": 0.024},
}

_IMAGE_TEXT_RELATION_OVERRIDES: dict[str, dict[str, object]] = {
    "separate": {"menu_overlap_ratio": 0.0},
    "overlap_subtle": {"menu_overlap_ratio": 0.08},
    "overlap_bold": {"menu_overlap_ratio": 0.16},
}

_HEADLINE_SCALE_OVERRIDES: dict[str, dict[str, object]] = {
    "small": {"headline_size_ratio": 0.042},
    "medium": {"headline_size_ratio": 0.050},
    "large": {"headline_size_ratio": 0.056},
}

_DEFAULT_TEMPLATE: dict[str, Any] = {
    "headline_size_ratio": 0.050,
    "subline_size_ratio": 0.034,
    "sticker_size_ratio": 0.028,
    "menu_size_ratio": 0.112,
    "price_size_ratio": 0.042,
    "store_size_ratio": 0.034,
    "headline_stroke_delta": 0,
    "headline_menu_gap_ratio": 0.014,
    "badge_style": "filled",
    "badge_pad_x_ratio": 0.034,
    "badge_pad_y_ratio": 0.016,
    "badge_outline_width_ratio": 0.0034,
    "price_cx_ratio": 0.76,
    "price_anchor": "top_right",
    "composition": "editorial",
    "price_style": "label",
    "menu_overlap_ratio": 0.12,
}

_TONE_TEMPLATE_DEFAULTS: dict[str, dict[str, Any]] = {
    "캐주얼·친근": {
        "headline_size_ratio": 0.052,
        "menu_size_ratio": 0.108,
        "price_size_ratio": 0.036,
        "store_size_ratio": 0.032,
        "badge_style": "filled",
        "composition": "centered",
        "price_style": "ticket",
        "menu_overlap_ratio": 0.04,
    },
    "정중·신뢰": {
        "headline_size_ratio": 0.046,
        "menu_size_ratio": 0.098,
        "price_size_ratio": 0.034,
        "store_size_ratio": 0.032,
        "badge_style": "filled",
        "badge_outline_width_ratio": 0.0030,
        "composition": "framed",
        "price_style": "ticket",
        "menu_overlap_ratio": 0.02,
    },
    "고급·감성": {
        "headline_size_ratio": 0.042,
        "subline_size_ratio": 0.030,
        "menu_size_ratio": 0.124,
        "price_size_ratio": 0.038,
        "store_size_ratio": 0.031,
        "headline_menu_gap_ratio": 0.018,
        "badge_style": "filled",
        "badge_pad_x_ratio": 0.036,
        "composition": "editorial",
        "price_style": "label",
        "menu_overlap_ratio": 0.08,
    },
    "유머·이벤트": {
        "headline_size_ratio": 0.054,
        "menu_size_ratio": 0.106,
        "price_size_ratio": 0.035,
        "store_size_ratio": 0.032,
        "badge_style": "filled",
        "badge_pad_x_ratio": 0.034,
        "badge_pad_y_ratio": 0.017,
        "composition": "centered",
        "price_style": "stamp",
        "menu_overlap_ratio": 0.06,
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
    composition: PosterComposition
    price_style: PosterPriceStyle
    menu_overlap_ratio: float


def resolve_poster_template(tone: str | None = None) -> PosterTemplateSpec:
    """
    톤·manifest 기반 포스터 템플릿 반환
    """

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

    composition = str(merged.get("composition", "editorial"))
    if composition not in ("editorial", "centered", "framed"):
        composition = "editorial"

    price_style = str(merged.get("price_style", "label"))
    if price_style not in ("label", "ticket", "stamp"):
        price_style = "label"

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
        composition=composition,  # type: ignore[arg-type]
        price_style=price_style,  # type: ignore[arg-type]
        menu_overlap_ratio=max(0.0, min(0.24, float(merged["menu_overlap_ratio"]))),
    )


_RATIO_BOUNDS: dict[str, tuple[float, float]] = {
    "headline_size_ratio": (0.032, 0.058),
    "subline_size_ratio": (0.026, 0.042),
    "sticker_size_ratio": (0.022, 0.034),
    "menu_size_ratio": (0.082, 0.128),
    "price_size_ratio": (0.030, 0.048),
    "store_size_ratio": (0.028, 0.044),
    "headline_menu_gap_ratio": (0.008, 0.030),
    "badge_pad_x_ratio": (0.020, 0.045),
    "badge_pad_y_ratio": (0.008, 0.020),
    "badge_outline_width_ratio": (0.0020, 0.0050),
    "price_cx_ratio": (0.55, 0.88),
    "menu_overlap_ratio": (0.0, 0.24),
}


def apply_template_overrides(
    base: PosterTemplateSpec,
    overrides: dict[str, object],
) -> PosterTemplateSpec:
    """
    검증된 디자인 토큰을 기존 템플릿 위에 merge
    """

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
        "composition": base.composition,
        "price_style": base.price_style,
        "menu_overlap_ratio": base.menu_overlap_ratio,
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

    composition = str(merged.get("composition", "editorial"))
    if composition not in ("editorial", "centered", "framed"):
        composition = "editorial"

    price_style = str(merged.get("price_style", "label"))
    if price_style not in ("label", "ticket", "stamp"):
        price_style = "label"

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
        composition=composition,  # type: ignore[arg-type]
        price_style=price_style,  # type: ignore[arg-type]
        menu_overlap_ratio=float(merged["menu_overlap_ratio"]),
    )


def build_semantic_template_overrides(
    *,
    template_id: object = None,
    density: object = None,
    image_text_relation: object = None,
    headline_scale: object = None,
) -> dict[str, object]:
    """
    VLM의 범주형 디자인 결정을 렌더러의 수치 토큰으로 변환
    """

    overrides: dict[str, object] = {}
    for value, choices in (
        (template_id, _TEMPLATE_ID_OVERRIDES),
        (density, _DENSITY_OVERRIDES),
        (image_text_relation, _IMAGE_TEXT_RELATION_OVERRIDES),
        (headline_scale, _HEADLINE_SCALE_OVERRIDES),
    ):
        if isinstance(value, str) and value in choices:
            overrides.update(choices[value])
    return overrides


def resolve_poster_template_for_layout(
    tone: str | None,
    *,
    vlm_overrides: Mapping[str, object] | None = None,
) -> PosterTemplateSpec:
    """
    톤 아트 디렉션을 보존하고, 톤이 없을 때만 VLM 구성을 적용
    """

    base = resolve_poster_template(tone)
    if not vlm_overrides:
        return base
    tone_key = _normalize_tone(tone)
    if tone_key in _TONE_TEMPLATE_DEFAULTS:
        return base
    return apply_template_overrides(base, dict(vlm_overrides))
