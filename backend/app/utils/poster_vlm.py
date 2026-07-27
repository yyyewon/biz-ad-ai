"""
포스터 디자인 VLM 분석
"""

from __future__ import annotations

import base64
import gc
import io
import json
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

from loguru import logger
from PIL import Image

from app.core.config import get_settings
from app.core.model_config import get_poster_design_model_settings
from app.schemas.performance_metrics import MetricId
from app.utils.memory_monitor import ensure_model_load_memory, log_model_memory_snapshot
from app.utils.performance_logger import record_registry_metric

_MODEL = None
_PROCESSOR = None
_VLM_LOCK = threading.RLock()
_INFERENCE_LOCK = threading.Lock()

# overlay 호출 시 VLM 재추론 대신 image_pipeline 배치 결과 사용
VLM_HINTS_AUTO = object()
VLM_HINTS_SKIP = object()

_SUBPROCESS_TIMEOUT_BASE_SECONDS = 120
_SUBPROCESS_TIMEOUT_PER_IMAGE_SECONDS = 180
_SUBPROCESS_TIMEOUT_MAX_SECONDS = 900

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


def poster_vlm_uses_gpu() -> bool:
    """True when poster VLM is configured to use CUDA (requires evicting Boogu first)."""
    model_config = get_poster_design_model_settings()
    if model_config is None:
        return False

    device_setting = str(model_config["settings"].get("device", "auto")).lower()
    if device_setting == "cpu":
        return False
    if device_setting in {"cuda", "gpu"}:
        return True

    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        return False


def poster_vlm_use_subprocess() -> bool:
    """
    GPU VLM을 isolated subprocess에서 실행할지 여부.
    model.yaml poster_design_analysis.use_subprocess: auto|true|false
    """
    model_config = get_poster_design_model_settings()
    if model_config is None:
        return False

    mode = str(model_config.get("use_subprocess", "auto")).lower()
    if mode in {"false", "0", "no", "off"}:
        return False
    if mode in {"true", "1", "yes", "on"}:
        return True
    return poster_vlm_uses_gpu()


def warm_up_poster_vlm() -> None:
    """
    서버 시작 시 VLM 가중치를 GPU(또는 설정된 device)에 미리 로드
    """

    model_config = get_poster_design_model_settings()
    if model_config is None:
        return

    if poster_vlm_use_subprocess():
        logger.info("poster_vlm_warmup_skipped | reason=subprocess_mode")
        return

    settings = model_config["settings"]
    model_id = str(settings["model_id"])
    _get_vlm_model(model_id=model_id, settings=settings)


def release_poster_vlm_gpu() -> None:
    """Drop cached poster VLM weights so Boogu image generation can use the full GPU."""
    global _MODEL, _PROCESSOR

    with _VLM_LOCK:
        if _MODEL is None and _PROCESSOR is None:
            logger.debug("poster_vlm_gpu_release_skipped | reason=not_loaded")
            return
        logger.info("poster_vlm_gpu_releasing")
        model = _MODEL
        processor = _PROCESSOR
        _MODEL = None
        _PROCESSOR = None

    _force_module_off_gpu(model)
    del model, processor
    gc.collect()
    _finalize_cuda_release()


def _force_module_off_gpu(module: object | None) -> None:
    if module is None:
        return
    try:
        from accelerate.hooks import remove_hook_from_submodules

        remove_hook_from_submodules(module)
    except Exception:
        pass
    try:
        import torch

        if hasattr(module, "hf_device_map"):
            module.hf_device_map = {}
        if hasattr(module, "to"):
            module.to("cpu")
        for param in getattr(module, "parameters", lambda: [])():
            if param.is_cuda:
                param.data = param.data.cpu()
                if param.grad is not None and param.grad.is_cuda:
                    param.grad = param.grad.cpu()
    except Exception as exc:
        logger.warning("poster_vlm_force_off_gpu_failed | error={}", str(exc))


def _finalize_cuda_release() -> None:
    gc.collect()
    try:
        import torch

        if not torch.cuda.is_available():
            return
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        ipc_collect = getattr(torch.cuda, "ipc_collect", None)
        if callable(ipc_collect):
            ipc_collect()
        gc.collect()
        torch.cuda.empty_cache()
    except ImportError:
        pass
    logger.info("poster_vlm_gpu_released")


def analyze_poster_design_with_vlm(
    image: Image.Image,
    *,
    metrics_request_id: str | None = None,
) -> PosterVlmDesignHints | None:
    """VLM으로 포스터 디자인 힌트를 분석한다. 실패 시 None."""
    results = analyze_poster_designs_batch([image], metrics_request_id=metrics_request_id)
    return results[0] if results else None


def analyze_poster_designs_batch(
    images: list[Image.Image],
    *,
    metrics_request_id: str | None = None,
) -> list[PosterVlmDesignHints | None]:
    """포스터 VLM 배치 분석. GPU 설정 시 subprocess에서 1회 load → N infer → exit."""

    if not images:
        return []

    model_config = get_poster_design_model_settings()
    if model_config is None:
        return [None] * len(images)

    request_id = metrics_request_id or "unknown"
    model_name = str(model_config.get("model_name", "unknown"))
    provider_name = str(model_config.get("provider", "hf"))
    inference_started = time.perf_counter()

    try:
        if poster_vlm_use_subprocess():
            raw_texts = _run_vlm_subprocess_batch(images, model_config=model_config)
        else:
            raw_texts = [
                _run_vlm_inference(image, model_config) for image in images
            ]

        elapsed_ms = (time.perf_counter() - inference_started) * 1000
        record_registry_metric(
            MetricId.VLM_INFERENCE_LATENCY,
            request_id=request_id,
            elapsed_ms=elapsed_ms,
            success=True,
            provider=provider_name,
            model=model_name,
            extra={"model": model_name, "image_count": len(images), "subprocess": poster_vlm_use_subprocess()},
        )

        hints_list: list[PosterVlmDesignHints | None] = []
        for image, raw_text in zip(images, raw_texts, strict=False):
            hints_list.append(
                _hints_from_raw_text(
                    raw_text,
                    image,
                    request_id=request_id,
                    model_name=model_name,
                    provider_name=provider_name,
                )
            )
        return hints_list

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - inference_started) * 1000
        record_registry_metric(
            MetricId.VLM_INFERENCE_LATENCY,
            request_id=request_id,
            elapsed_ms=elapsed_ms,
            success=False,
            provider=provider_name,
            model=model_name,
            error_type=exc.__class__.__name__,
            extra={"model": model_name, "image_count": len(images), "subprocess": poster_vlm_use_subprocess()},
        )
        record_registry_metric(
            MetricId.VLM_JSON_PARSE_SUCCESS_RATE,
            request_id=request_id,
            success=False,
            provider=provider_name,
            model=model_name,
            error_type=exc.__class__.__name__,
            extra={"model": model_name},
        )
        logger.warning("poster_vlm_batch_failed | error={}", str(exc))
        return [None] * len(images)


def _hints_from_raw_text(
    raw_text: str | None,
    image: Image.Image,
    *,
    request_id: str,
    model_name: str,
    provider_name: str,
) -> PosterVlmDesignHints | None:
    if not raw_text:
        record_registry_metric(
            MetricId.VLM_JSON_PARSE_SUCCESS_RATE,
            request_id=request_id,
            success=False,
            provider=provider_name,
            model=model_name,
            extra={"model": model_name, "raw_chars": 0},
        )
        return None

    logger.debug("poster_vlm_raw_response | chars={} | text={}", len(raw_text), raw_text[:500])
    parsed = parse_poster_vlm_json(raw_text)
    if parsed is None:
        logger.warning(
            "poster_vlm_parse_failed | raw_chars={} | preview={}",
            len(raw_text),
            raw_text[:300],
        )
        record_registry_metric(
            MetricId.VLM_JSON_PARSE_SUCCESS_RATE,
            request_id=request_id,
            success=False,
            provider=provider_name,
            model=model_name,
            extra={"model": model_name, "raw_chars": len(raw_text)},
        )
        return None

    record_registry_metric(
        MetricId.VLM_JSON_PARSE_SUCCESS_RATE,
        request_id=request_id,
        success=True,
        provider=provider_name,
        model=model_name,
        extra={"model": model_name, "raw_chars": len(raw_text)},
    )

    width, height = image.size
    hints = _build_hints_from_parsed(parsed, width=width, height=height)
    logger.info(
        "poster_vlm_json | model={} | payload={}",
        model_name,
        json.dumps(parsed, ensure_ascii=False),
    )
    logger.info(
        "poster_vlm_applied | model={} | primary_text={} | scrim_alpha={}",
        model_name,
        hints.palette.primary_text,
        hints.scrim_max_alpha,
    )
    return hints


def _run_vlm_subprocess_batch(
    images: list[Image.Image],
    *,
    model_config: dict,
) -> list[str | None]:
    settings = dict(model_config["settings"])
    encoded_images: list[dict] = []
    for image in images:
        rgb = image.convert("RGB")
        buffer = io.BytesIO()
        rgb.save(buffer, format="PNG")
        encoded_images.append(
            {
                "width": rgb.size[0],
                "height": rgb.size[1],
                "png_b64": base64.b64encode(buffer.getvalue()).decode("ascii"),
            }
        )

    timeout = min(
        _SUBPROCESS_TIMEOUT_MAX_SECONDS,
        max(
            _SUBPROCESS_TIMEOUT_BASE_SECONDS,
            _SUBPROCESS_TIMEOUT_PER_IMAGE_SECONDS * len(images),
        ),
    )

    logger.info(
        "poster_vlm_subprocess_started | image_count={} | timeout_seconds={}",
        len(images),
        timeout,
    )

    cmd = [sys.executable, "-m", "app.utils.poster_vlm_worker"]
    request_payload = json.dumps(
        {"settings": settings, "images": encoded_images},
        ensure_ascii=False,
    )

    completed = subprocess.run(
        cmd,
        input=request_payload,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise RuntimeError(
            f"포스터 VLM subprocess 실패 (exit_code={completed.returncode}) | stderr={stderr[:500]}"
        )

    stdout = (completed.stdout or "").strip()
    if not stdout:
        raise RuntimeError("포스터 VLM subprocess가 stdout을 반환하지 않았습니다.")

    response = json.loads(stdout)
    if not response.get("ok"):
        raise RuntimeError(response.get("error") or "포스터 VLM subprocess 처리 중 오류가 발생했습니다.")

    results = response.get("results")
    if not isinstance(results, list):
        raise RuntimeError("포스터 VLM subprocess 결과 형식이 올바르지 않습니다.")

    raw_texts: list[str | None] = []
    for entry in results:
        if isinstance(entry, dict) and entry.get("ok") and entry.get("raw_text"):
            raw_texts.append(str(entry["raw_text"]))
        else:
            error = entry.get("error") if isinstance(entry, dict) else "알 수 없음"
            logger.warning("poster_vlm_subprocess_image_failed | error={}", error)
            raw_texts.append(None)

    while len(raw_texts) < len(images):
        raw_texts.append(None)

    logger.info(
        "poster_vlm_subprocess_completed | image_count={} | success_count={}",
        len(images),
        sum(1 for item in raw_texts if item),
    )
    return raw_texts[: len(images)]


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
    model, processor = _get_vlm_model(model_id=model_id, settings=settings)
    return run_vlm_inference_with_model(
        image,
        model=model,
        processor=processor,
        model_config=model_config,
    )


def run_vlm_inference_with_model(
    image: Image.Image,
    *,
    model: object,
    processor: object,
    model_config: dict,
) -> str:
    settings = model_config["settings"]
    max_new_tokens = int(settings.get("max_new_tokens", 512))
    max_side = int(settings.get("analysis_max_side", 768))

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


def load_vlm_model_fresh(model_config: dict) -> tuple[object, object]:
    """Subprocess 워커용: global cache 없이 VLM을 1회 로드한다."""
    settings = model_config["settings"]
    model_id = str(settings["model_id"])
    return _load_vlm_model_impl(model_id=model_id, settings=settings)


def _get_vlm_model(*, model_id: str, settings: dict):
    global _MODEL, _PROCESSOR

    with _VLM_LOCK:
        if _MODEL is not None and _PROCESSOR is not None:
            return _MODEL, _PROCESSOR

        model, processor = _load_vlm_model_impl(model_id=model_id, settings=settings)
        _MODEL = model
        _PROCESSOR = processor
        return _MODEL, _PROCESSOR


def _load_vlm_model_impl(*, model_id: str, settings: dict) -> tuple[object, object]:
    before_load = log_model_memory_snapshot(
        "before_poster_vlm_load",
        model_name=model_id,
    )
    ensure_model_load_memory(
        model_name=model_id,
        min_available_ram_gb=get_settings().model_load_min_available_ram_gb,
        load_stage="before_poster_vlm_load",
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

    if device_setting == "cpu":
        _force_module_off_gpu(model)

    cuda_param_count = sum(
        1 for param in model.parameters() if getattr(param, "is_cuda", False)
    )
    logger.info(
        "poster_vlm_loaded | model_id={} | device_map={} | cuda_param_count={}",
        model_id,
        device_map,
        cuda_param_count,
    )

    log_model_memory_snapshot(
        "after_poster_vlm_load",
        model_name=model_id,
        torch_module=torch,
    )
    return model, processor


def _resize_for_analysis(image: Image.Image, *, max_side: int) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image

    scale = max_side / longest
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)
