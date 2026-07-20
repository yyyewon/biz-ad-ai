"""
포스터 디자인 VLM 분석.

생성된 포스터 이미지를 보고 palette·배치·scrim 힌트 JSON을 반환한다.
실패 시 None → poster_layout 규칙 기반 fallback.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass

from loguru import logger
from PIL import Image

from app.core.model_config import get_poster_design_model_settings

_MODEL = None
_PROCESSOR = None
_VLM_LOCK = threading.RLock()
_INFERENCE_LOCK = threading.Lock()

_POSTER_VLM_PROMPT = """\
This is a food promo poster image: designed background on top, food hero on bottom. \
There is NO text in the image yet. We will add Korean headline, menu name, price pill, \
and store name with PIL.

Return ONLY one JSON object (no markdown) for text overlay design:
{
  "palette": {
    "primary_text_rgb": [r, g, b],
    "primary_stroke_rgb": [r, g, b],
    "store_text_rgb": [r, g, b],
    "store_stroke_rgb": [r, g, b],
    "badge_text_rgb": [r, g, b],
    "badge_outline_rgb": [r, g, b]
  },
  "layout": {
    "price_badge_cx_ratio": 0.76,
    "price_badge_cy_ratio": 0.16,
    "price_anchor": "menu_right"
  },
  "typography": {
    "headline_size_ratio": 0.030,
    "menu_size_ratio": 0.092,
    "price_size_ratio": 0.034,
    "store_size_ratio": 0.032,
    "headline_menu_gap_ratio": 0.016,
    "badge_style": "outline"
  },
  "scrim": {
    "height_ratio": 0.32,
    "max_alpha": 80
  }
}

Rules:
- Analyze the TOP background area (not the food) for headline/menu/price colors.
- Analyze the BOTTOM-RIGHT background for store name colors.
- NEVER set every RGB field to [255, 255, 255] or identical values.
- On light/beige backgrounds use DARK text (e.g. [60, 40, 30]); on dark backgrounds use LIGHT text.
- Text colors should harmonize with the BACKGROUND hue (not food colors).
- Ratios are 0.0-1.0 relative to image width/height.
- typography.headline_size_ratio should be smaller than typography.menu_size_ratio.
- typography.badge_style must be "outline" or "filled".
- layout.price_anchor must be "menu_right" or "layout".
- scrim.max_alpha is 0-150 (use 60-120 on busy or light backgrounds).
- Use readable contrast; stroke must contrast with both text and background.
"""


@dataclass(frozen=True)
class PosterVlmDesignHints:
    palette: "PosterPaletteSpec"
    price_badge_cx: int | None = None
    price_badge_cy_hint: int | None = None
    scrim_height: int | None = None
    scrim_max_alpha: int | None = None
    template: "PosterTemplateSpec | None" = None


def is_poster_vlm_enabled() -> bool:
    return get_poster_design_model_settings() is not None


def analyze_poster_design_with_vlm(image: Image.Image) -> PosterVlmDesignHints | None:
    """VLM으로 포스터 디자인 힌트를 분석한다. 실패 시 None."""

    model_config = get_poster_design_model_settings()
    if model_config is None:
        return None

    try:
        raw_text = _run_vlm_inference(image, model_config)
        logger.debug("poster_vlm_raw_response | chars={} | text={}", len(raw_text), raw_text[:500])
        parsed = parse_poster_vlm_json(raw_text)
        if parsed is None:
            logger.warning(
                "poster_vlm_parse_failed | raw_chars={} | preview={}",
                len(raw_text),
                raw_text[:300],
            )
            return None

        width, height = image.size
        hints = _build_hints_from_parsed(parsed, width=width, height=height)
        logger.info(
            "poster_vlm_json | model={} | payload={}",
            model_config["model_name"],
            json.dumps(parsed, ensure_ascii=False),
        )
        logger.info(
            "poster_vlm_applied | model={} | primary_text={} | price_cx={} | scrim_alpha={} | badge_style={}",
            model_config["model_name"],
            hints.palette.primary_text,
            hints.price_badge_cx,
            hints.scrim_max_alpha,
            hints.template.badge_style if hints.template else None,
        )
        return hints

    except Exception as exc:
        logger.warning("poster_vlm_failed | error={}", str(exc))
        return None


def parse_poster_vlm_json(raw_text: str) -> dict | None:
    """VLM 응답에서 JSON 객체를 추출한다."""

    text = (raw_text or "").strip()
    if not text:
        return None

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None

    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None

    return payload if isinstance(payload, dict) else None


def _build_hints_from_parsed(
    payload: dict,
    *,
    width: int,
    height: int,
) -> PosterVlmDesignHints:
    from app.utils.poster_layout import PosterPaletteSpec

    palette_block = payload.get("palette", {})
    if not isinstance(palette_block, dict):
        palette_block = {}

    palette = PosterPaletteSpec(
        primary_text=_parse_rgb(palette_block.get("primary_text_rgb"), default=(80, 45, 20)),
        primary_stroke=_parse_rgb(palette_block.get("primary_stroke_rgb"), default=(255, 255, 255)),
        store_text=_parse_rgb(palette_block.get("store_text_rgb"), default=(80, 45, 20)),
        store_stroke=_parse_rgb(palette_block.get("store_stroke_rgb"), default=(255, 255, 255)),
        badge_text=_parse_rgb(
            palette_block.get("badge_text_rgb"),
            default=_parse_rgb(palette_block.get("primary_text_rgb"), default=(80, 45, 20)),
        ),
        badge_outline=_parse_rgb(
            palette_block.get("badge_outline_rgb"),
            default=_parse_rgb(palette_block.get("primary_text_rgb"), default=(80, 45, 20)),
        ),
    )

    layout_block = payload.get("layout", {})
    typography_block = payload.get("typography", {})
    scrim_block = payload.get("scrim", {})
    if not isinstance(layout_block, dict):
        layout_block = {}
    if not isinstance(typography_block, dict):
        typography_block = {}
    if not isinstance(scrim_block, dict):
        scrim_block = {}

    price_cx = _parse_ratio(layout_block.get("price_badge_cx_ratio"))
    price_cy = _parse_ratio(layout_block.get("price_badge_cy_ratio"))
    scrim_h = _parse_ratio(scrim_block.get("height_ratio"))
    scrim_alpha = _parse_int(scrim_block.get("max_alpha"), min_value=0, max_value=150)

    template = _build_template_from_vlm(typography_block, layout_block)

    return PosterVlmDesignHints(
        palette=palette,
        price_badge_cx=int(width * price_cx) if price_cx is not None else None,
        price_badge_cy_hint=int(height * price_cy) if price_cy is not None else None,
        scrim_height=int(height * scrim_h) if scrim_h is not None else None,
        scrim_max_alpha=scrim_alpha,
        template=template,
    )


def _build_template_from_vlm(
    typography_block: dict,
    layout_block: dict,
) -> "PosterTemplateSpec | None":
    from app.utils.poster_template import apply_template_overrides, resolve_poster_template

    overrides: dict[str, object] = {}
    for key in (
        "headline_size_ratio",
        "menu_size_ratio",
        "price_size_ratio",
        "store_size_ratio",
        "headline_menu_gap_ratio",
        "badge_pad_x_ratio",
        "badge_pad_y_ratio",
        "badge_outline_width_ratio",
        "price_cx_ratio",
    ):
        ratio = _parse_ratio(typography_block.get(key))
        if ratio is not None:
            overrides[key] = ratio

    headline_stroke_delta = _parse_int(
        typography_block.get("headline_stroke_delta"),
        min_value=-3,
        max_value=3,
    )
    if headline_stroke_delta is not None:
        overrides["headline_stroke_delta"] = headline_stroke_delta

    badge_style = typography_block.get("badge_style")
    if isinstance(badge_style, str) and badge_style in ("outline", "filled"):
        overrides["badge_style"] = badge_style

    price_anchor = layout_block.get("price_anchor")
    if isinstance(price_anchor, str) and price_anchor in ("menu_right", "layout"):
        overrides["price_anchor"] = price_anchor

    price_cx_ratio = _parse_ratio(layout_block.get("price_badge_cx_ratio"))
    if price_cx_ratio is not None:
        overrides["price_cx_ratio"] = price_cx_ratio

    if not overrides:
        return None

    return apply_template_overrides(resolve_poster_template(None), overrides)


def _parse_rgb(value: object, *, default: tuple[int, int, int]) -> tuple[int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return default
    try:
        channels = tuple(max(0, min(255, int(channel))) for channel in value)
    except (TypeError, ValueError):
        return default
    return channels  # type: ignore[return-value]


def _parse_ratio(value: object) -> float | None:
    try:
        ratio = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, ratio))


def _parse_int(
    value: object,
    *,
    min_value: int,
    max_value: int,
) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(min_value, min(max_value, number))


def _run_vlm_inference(image: Image.Image, model_config: dict) -> str:
    settings = model_config["settings"]
    model_id = str(settings["model_id"])
    max_new_tokens = int(settings.get("max_new_tokens", 512))
    max_side = int(settings.get("analysis_max_side", 768))

    model, processor = _get_vlm_model(model_id=model_id, settings=settings)
    resized = _resize_for_analysis(image.convert("RGB"), max_side=max_side)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": resized},
                {"type": "text", "text": _POSTER_VLM_PROMPT},
            ],
        }
    ]

    try:
        from qwen_vl_utils import process_vision_info

        text = processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )
    except ImportError:
        inputs = processor(
            text=[_POSTER_VLM_PROMPT],
            images=[resized],
            return_tensors="pt",
        )

    import torch

    device = next(model.parameters()).device
    inputs = inputs.to(device)

    with _INFERENCE_LOCK:
        with torch.inference_mode():
            output_ids = model.generate(**inputs, max_new_tokens=max_new_tokens)

    trimmed = [
        out_ids[len(in_ids) :]
        for in_ids, out_ids in zip(inputs.input_ids, output_ids, strict=False)
    ]
    return processor.batch_decode(
        trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]


def _ensure_gptq_runtime(model_id: str) -> None:
    """GPTQ 체크포인트 로딩에 필요한 런타임을 준비한다."""

    if "gptq" not in model_id.lower():
        return

    try:
        import gptqmodel  # noqa: F401 — 5.8+ HF 네이티브 연동 등록
    except ImportError as exc:
        raise ImportError(
            "GPTQ VLM requires `pip install optimum gptqmodel qwen-vl-utils`"
        ) from exc

    # gptqmodel <5.8: patch_hf 필요. 5.8+는 제거됨(네이티브 HF/Optimum 연동).
    try:
        from gptqmodel import patch_hf

        patch_hf()
    except ImportError:
        logger.debug("gptqmodel patch_hf skipped (native HF integration)")


def _get_vlm_model(*, model_id: str, settings: dict):
    global _MODEL, _PROCESSOR

    with _VLM_LOCK:
        if _MODEL is not None and _PROCESSOR is not None:
            return _MODEL, _PROCESSOR

        import torch
        from transformers import AutoProcessor, Qwen2VLForConditionalGeneration

        device_setting = str(settings.get("device", "auto")).lower()
        if device_setting == "auto":
            device_map = "auto"
        elif device_setting == "cpu":
            device_map = "cpu"
        else:
            device_map = "auto"

        logger.info("poster_vlm_loading | model_id={} | device_map={}", model_id, device_map)

        _ensure_gptq_runtime(model_id)
        processor = AutoProcessor.from_pretrained(model_id)
        model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_id,
            torch_dtype="auto",
            device_map=device_map,
        )
        model.eval()

        _MODEL = model
        _PROCESSOR = processor
        logger.info("poster_vlm_loaded | model_id={}", model_id)
        return _MODEL, _PROCESSOR


def _resize_for_analysis(image: Image.Image, *, max_side: int) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image

    scale = max_side / longest
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)
