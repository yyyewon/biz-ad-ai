"""
이미지 오버레이용 폰트 레지스트리.

backend/assets/fonts/ 번들 폰트와 manifest.json 설정을 사용한다.
"""
from __future__ import annotations

import json
import threading
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from loguru import logger
from PIL import ImageFont

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
FONTS_DIR = _BACKEND_ROOT / "assets" / "fonts"
MANIFEST_PATH = FONTS_DIR / "manifest.json"

_download_lock = threading.Lock()


class TextOverlayRole(StrEnum):
    POSTER_HEADLINE = "poster_headline"
    POSTER_MENU = "poster_menu"
    POSTER_PRICE = "poster_price"
    POSTER_STORE = "poster_store"
    REELS_HOOK_LEAD = "reels_hook_lead"
    REELS_HOOK = "reels_hook"


POSTER_ROLES = frozenset({
    TextOverlayRole.POSTER_HEADLINE,
    TextOverlayRole.POSTER_MENU,
    TextOverlayRole.POSTER_PRICE,
    TextOverlayRole.POSTER_STORE,
})


# 가변 폰트(wght) 기본값이 100이라 얇게 나오므로 역할별 굵기를 지정한다.
ROLE_FONT_WEIGHTS: dict[str, int] = {
    TextOverlayRole.POSTER_HEADLINE: 500,
    TextOverlayRole.POSTER_MENU: 800,
    TextOverlayRole.POSTER_PRICE: 700,
    TextOverlayRole.POSTER_STORE: 400,
    TextOverlayRole.REELS_HOOK_LEAD: 400,
    TextOverlayRole.REELS_HOOK: 800,
}


def _normalize_tone(tone: str | None) -> str | None:
    if tone is None:
        return None
    normalized = str(tone).strip()
    return normalized or None


def _get_tone_block(manifest: dict[str, Any], tone: str | None) -> dict[str, Any] | None:
    tone_key = _normalize_tone(tone)
    if not tone_key:
        return None

    tone_block = manifest.get("tone_overrides", {}).get(tone_key)
    if isinstance(tone_block, dict):
        return tone_block
    return None


def _resolve_tone_role_style(
    manifest: dict[str, Any],
    tone: str | None,
    role_name: str,
) -> dict[str, Any] | None:
    if role_name not in POSTER_ROLES:
        return None

    tone_block = _get_tone_block(manifest, tone)
    if tone_block is None:
        return None

    tone_font = tone_block.get("font")
    role_style = tone_block.get(role_name)

    merged: dict[str, Any] = {}
    if isinstance(role_style, dict):
        merged.update(role_style)
    if "font" not in merged and tone_font:
        merged["font"] = tone_font

    return merged or None


def _resolve_font_weight(
    role: TextOverlayRole | str,
    *,
    tone: str | None = None,
    food_type: str | None = None,
    variant: str | None = None,
) -> int:
    manifest = _load_manifest()
    role_name = str(role)

    tone_style = _resolve_tone_role_style(manifest, tone, role_name)
    if tone_style is not None and tone_style.get("weight") is not None:
        return int(tone_style["weight"])

    if food_type:
        food_overrides = manifest.get("food_type_overrides", {}).get(food_type, {})
        variant_roles = food_overrides.get(variant or "", {})
        if role_name in variant_roles and isinstance(variant_roles[role_name], dict):
            weight = variant_roles[role_name].get("weight")
            if weight is not None:
                return int(weight)

    role_styles = manifest.get("role_styles", {})
    if role_name in role_styles and "weight" in role_styles[role_name]:
        return int(role_styles[role_name]["weight"])

    return ROLE_FONT_WEIGHTS.get(role_name, 400)


def _apply_font_weight(font: ImageFont.FreeTypeFont, weight: int) -> ImageFont.FreeTypeFont:
    if not hasattr(font, "get_variation_axes"):
        return font

    try:
        axes = font.get_variation_axes()
    except OSError:
        return font

    if not axes:
        return font

    font.set_variation_by_axes([weight])
    return font


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"폰트 manifest 파일을 찾을 수 없습니다: {MANIFEST_PATH}")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def list_font_keys() -> list[str]:
    manifest = _load_manifest()
    return list(manifest.get("fonts", {}).keys())


def list_required_font_keys(
    *,
    tone: str | None = None,
    food_type: str | None = None,
    variant: str | None = None,
) -> list[str]:
    manifest = _load_manifest()
    roles = manifest.get("roles", {})
    font_keys = {roles[role] for role in roles}

    tone_key = _normalize_tone(tone)
    if tone_key:
        tone_block = manifest.get("tone_overrides", {}).get(tone_key, {})
        tone_font = tone_block.get("font")
        if tone_font:
            font_keys.add(tone_font)

        for role_name, role_style in tone_block.items():
            if role_name in POSTER_ROLES and isinstance(role_style, dict):
                font_key = role_style.get("font")
                if font_key:
                    font_keys.add(font_key)

    if food_type:
        overrides = manifest.get("food_type_overrides", {}).get(food_type, {})
        if variant and variant in overrides:
            font_keys.update(overrides[variant].values())
        elif not variant:
            for variant_roles in overrides.values():
                font_keys.update(variant_roles.values())

    return sorted(font_keys)


def resolve_font_key(
    role: TextOverlayRole | str,
    *,
    tone: str | None = None,
    food_type: str | None = None,
    variant: str | None = None,
) -> str:
    manifest = _load_manifest()
    role_name = str(role)

    tone_style = _resolve_tone_role_style(manifest, tone, role_name)
    if tone_style is not None and tone_style.get("font"):
        return str(tone_style["font"])

    if food_type:
        food_overrides = manifest.get("food_type_overrides", {}).get(food_type, {})
        if variant and variant in food_overrides and role_name in food_overrides[variant]:
            return food_overrides[variant][role_name]
        if role_name in food_overrides:
            return food_overrides[role_name]

    roles = manifest.get("roles", {})
    if role_name not in roles:
        raise KeyError(f"알 수 없는 텍스트 오버레이 역할입니다: {role_name}")
    return roles[role_name]


def resolve_font_path(
    role: TextOverlayRole | str,
    *,
    tone: str | None = None,
    food_type: str | None = None,
    variant: str | None = None,
) -> Path:
    manifest = _load_manifest()
    font_key = resolve_font_key(
        role,
        tone=tone,
        food_type=food_type,
        variant=variant,
    )
    font_entry = manifest["fonts"][font_key]
    return FONTS_DIR / font_entry["filename"]


def _download_font(font_key: str) -> Path:
    manifest = _load_manifest()
    font_entry = manifest["fonts"][font_key]
    target_path = FONTS_DIR / font_entry["filename"]
    url = font_entry["url"]

    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("font_download_started | key={} | url={}", font_key, url)

    try:
        with urlopen(url, timeout=60) as response:
            data = response.read()
    except URLError as exc:
        raise RuntimeError(f"폰트 다운로드에 실패했습니다: {font_key} ({url})") from exc

    target_path.write_bytes(data)
    logger.info(
        "font_download_completed | key={} | path={} | bytes={}",
        font_key,
        target_path,
        len(data),
    )
    return target_path


def ensure_fonts_installed(
    font_keys: list[str] | None = None,
    *,
    tone: str | None = None,
    food_type: str | None = None,
    variant: str | None = None,
) -> list[Path]:
    """
    manifest에 등록된 폰트 파일이 없으면 다운로드한다.
    `python scripts/setup_fonts.py`와 동일한 역할을 한다.
    """
    keys = font_keys or list_required_font_keys(
        tone=tone,
        food_type=food_type,
        variant=variant,
    )
    installed: list[Path] = []

    with _download_lock:
        for font_key in keys:
            manifest = _load_manifest()
            target_path = FONTS_DIR / manifest["fonts"][font_key]["filename"]
            if target_path.is_file() and target_path.stat().st_size > 0:
                installed.append(target_path)
                continue
            installed.append(_download_font(font_key))

    return installed


@lru_cache(maxsize=128)
def load_overlay_font(
    role: TextOverlayRole | str,
    size: int,
    *,
    tone: str | None = None,
    food_type: str | None = None,
    variant: str | None = None,
) -> ImageFont.FreeTypeFont:
    font_key = resolve_font_key(
        role,
        tone=tone,
        food_type=food_type,
        variant=variant,
    )
    ensure_fonts_installed(font_keys=[font_key])
    font_path = resolve_font_path(
        role,
        tone=tone,
        food_type=food_type,
        variant=variant,
    )
    weight = _resolve_font_weight(
        role,
        tone=tone,
        food_type=food_type,
        variant=variant,
    )

    try:
        font = ImageFont.truetype(str(font_path), size=size)
        return _apply_font_weight(font, weight)
    except OSError as exc:
        raise RuntimeError(f"오버레이 폰트를 불러오지 못했습니다: {font_path}") from exc
