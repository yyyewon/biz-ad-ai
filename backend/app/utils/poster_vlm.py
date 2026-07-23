"""
포스터 디자인 VLM 분석
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass

from loguru import logger
from PIL import Image

from app.core.config import get_settings
from app.core.model_config import get_poster_design_model_settings
from app.utils.memory_monitor import ensure_model_load_memory, log_model_memory_snapshot

_MODEL = None
_PROCESSOR = None
_VLM_LOCK = threading.RLock()
_INFERENCE_LOCK = threading.Lock()

_POSTER_VLM_PROMPT = """\
This is a food promo poster image: designed background on top, food hero on bottom. \
There is NO text in the image yet. We will add Korean headline, menu name, price component, \
and store name with PIL.

Return ONLY one JSON object (no markdown) for text overlay design:
{
  "palette": {
    "primary_text_rgb": [r, g, b],
    "primary_stroke_rgb": [r, g, b],
    "accent_text_rgb": [r, g, b],
    "store_text_rgb": [r, g, b],
    "store_stroke_rgb": [r, g, b],
    "badge_fill_rgb": [r, g, b],
    "badge_text_rgb": [r, g, b],
    "badge_outline_rgb": [r, g, b]
  },
  "design": {
    "template_id": "editorial",
    "density": "airy",
    "image_text_relation": "overlap_subtle",
    "headline_scale": "medium"
  },
  "scrim": {
    "height_ratio": 0.32,
    "max_alpha": 80
  }
}

Rules:
- Analyze the TOP background area for headline/subline colors (primary_text).
- accent_text_rgb is for the MENU name: slightly richer than primary, may echo food hue.
- badge_fill_rgb is the price pill BACKGROUND (cream/off-white, e.g. [248, 245, 238]).
- badge_text_rgb must contrast with badge_fill_rgb (dark on cream).
- Analyze the BOTTOM-RIGHT background for store name colors (muted, weaker than accent).
- NEVER set every RGB field to [255, 255, 255] or identical values.
- On light/beige backgrounds use DARK text (e.g. [60, 40, 30]); on dark backgrounds use LIGHT text.
- Text colors should harmonize with the BACKGROUND hue for primary/store; accent may be warmer.
- Choose template_id from: editorial, centered, framed.
  - editorial: asymmetric image or useful side space; bold magazine-like hierarchy.
  - centered: centered/symmetric food hero and balanced top space.
  - framed: calm, traditional, or evenly textured background that suits a border.
- Choose density from: compact, balanced, airy. Use airy only with generous clean space.
- Choose image_text_relation from: separate, overlap_subtle, overlap_bold.
  Use overlap only when the food edge is clear enough for readable outlined text.
- Choose headline_scale from: small, medium, large.
- Do NOT output x/y coordinates or numeric font sizes. The renderer measures text and decides them.
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
    template_overrides: dict[str, object] | None = None


def is_poster_vlm_enabled() -> bool:
    return get_poster_design_model_settings() is not None


def warm_up_poster_vlm() -> None:
    """
    서버 시작 시 VLM 가중치를 GPU(또는 설정된 device)에 미리 로드
    """

    model_config = get_poster_design_model_settings()
    if model_config is None:
        return

    settings = model_config["settings"]
    model_id = str(settings["model_id"])
    _get_vlm_model(model_id=model_id, settings=settings)


def analyze_poster_design_with_vlm(image: Image.Image) -> PosterVlmDesignHints | None:
    """
    VLM으로 포스터 디자인 힌트 분석
    """

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
            "poster_vlm_applied | model={} | primary_text={} | scrim_alpha={}",
            model_config["model_name"],
            hints.palette.primary_text,
            hints.scrim_max_alpha,
        )
        return hints

    except Exception as exc:
        logger.warning("poster_vlm_failed | error={}", str(exc))
        return None


def parse_poster_vlm_json(raw_text: str) -> dict | None:
    """
    VLM 응답에서 JSON 객체 추출
    """

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

    primary_default = (80, 45, 20)
    accent_default = (120, 72, 28)
    badge_fill_default = (248, 245, 238)

    palette = PosterPaletteSpec(
        primary_text=_parse_rgb(palette_block.get("primary_text_rgb"), default=primary_default),
        primary_stroke=_parse_rgb(palette_block.get("primary_stroke_rgb"), default=(255, 255, 255)),
        accent_text=_parse_rgb(
            palette_block.get("accent_text_rgb"),
            default=_parse_rgb(palette_block.get("primary_text_rgb"), default=accent_default),
        ),
        store_text=_parse_rgb(palette_block.get("store_text_rgb"), default=primary_default),
        store_stroke=_parse_rgb(palette_block.get("store_stroke_rgb"), default=(255, 255, 255)),
        badge_fill=_parse_rgb(
            palette_block.get("badge_fill_rgb"),
            default=badge_fill_default,
        ),
        badge_text=_parse_rgb(
            palette_block.get("badge_text_rgb"),
            default=_parse_rgb(palette_block.get("accent_text_rgb"), default=accent_default),
        ),
        badge_outline=_parse_rgb(
            palette_block.get("badge_outline_rgb"),
            default=_parse_rgb(palette_block.get("accent_text_rgb"), default=accent_default),
        ),
    )

    design_block = payload.get("design", {})
    scrim_block = payload.get("scrim", {})
    if not isinstance(design_block, dict):
        design_block = {}
    if not isinstance(scrim_block, dict):
        scrim_block = {}

    scrim_h = _parse_ratio(scrim_block.get("height_ratio"))
    scrim_alpha = _parse_int(scrim_block.get("max_alpha"), min_value=0, max_value=150)
    template_overrides = _build_template_overrides_from_vlm(design_block)

    return PosterVlmDesignHints(
        palette=palette,
        scrim_height=int(height * scrim_h) if scrim_h is not None else None,
        scrim_max_alpha=scrim_alpha,
        template_overrides=template_overrides,
    )


def _build_template_overrides_from_vlm(design_block: dict) -> dict[str, object] | None:
    from app.utils.poster_template import build_semantic_template_overrides

    overrides = build_semantic_template_overrides(
        template_id=design_block.get("template_id"),
        density=design_block.get("density"),
        image_text_relation=design_block.get("image_text_relation"),
        headline_scale=design_block.get("headline_scale"),
    )
    return overrides or None


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
        import gptqmodel
    except ImportError as exc:
        raise ImportError(
            "GPTQ VLM requires `pip install optimum gptqmodel qwen-vl-utils`"
        ) from exc

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

        before_load = log_model_memory_snapshot(
            "before_poster_vlm_load",
            model_name=model_id,
        )
        ensure_model_load_memory(
            model_name=model_id,
            min_available_ram_gb=get_settings().model_load_min_available_ram_gb,
            snapshot=before_load,
        )

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
        log_model_memory_snapshot(
            "after_poster_vlm_load",
            model_name=model_id,
            torch_module=torch,
        )
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
