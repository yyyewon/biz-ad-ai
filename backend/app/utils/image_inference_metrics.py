"""
Image provider inference-only latency (pipe/API call), excluding model load.

Providers call record_image_inference_latency() per inference segment.
image_pipeline reads consume_image_inference_accumulator_ms() for variant_generation.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from app.schemas.performance_metrics import MetricId
from app.utils.performance_logger import record_performance_metric, record_registry_metric

_inference_accumulator_ms: ContextVar[int] = ContextVar(
    "image_inference_accumulator_ms",
    default=0,
)

_HF_PROVIDER_TYPES = frozenset(
    {
        "sdxl_lightning",
        "sdxl_ip_adapter",
        "sd15_controlnet_tile",
        "sdxl_base",
        "hf_image",
    }
)


def reset_image_inference_accumulator() -> None:
    _inference_accumulator_ms.set(0)


def consume_image_inference_accumulator_ms() -> int:
    return int(_inference_accumulator_ms.get())


def _accumulate_image_inference_ms(elapsed_ms: float) -> None:
    current = _inference_accumulator_ms.get()
    _inference_accumulator_ms.set(current + int(round(elapsed_ms)))


def record_image_inference_latency(
    *,
    request_id: str,
    provider: str,
    model: str,
    elapsed_ms: float,
    success: bool,
    provider_type: str | None = None,
    extra: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_type: str | None = None,
) -> None:
    """
    Record one inference segment (diffusion pipe() or OpenAI images API call).

    Model load / download time must be recorded separately via model_load metrics.
    """

    if success:
        _accumulate_image_inference_ms(elapsed_ms)

    merged_extra: dict[str, Any] = dict(extra or {})
    if provider_type:
        merged_extra.setdefault("provider_type", provider_type)
    merged_extra.setdefault("measurement", "inference_only")

    record_registry_metric(
        MetricId.IMAGE_INFERENCE_LATENCY,
        request_id=request_id,
        elapsed_ms=elapsed_ms,
        success=success,
        provider=provider,
        model=model,
        extra=merged_extra or None,
        error_code=error_code,
        error_type=error_type,
    )

    record_performance_metric(
        pipeline="ad_generate",
        stage="inference",
        request_id=request_id,
        provider=provider,
        model=model,
        elapsed_ms=elapsed_ms,
        success=success,
        extra=merged_extra or None,
        error_code=error_code,
        error_type=error_type,
    )

    if provider_type == "boogu_edit":
        record_registry_metric(
            MetricId.BOOGU_INFERENCE_LATENCY,
            request_id=request_id,
            elapsed_ms=elapsed_ms,
            success=success,
            provider=provider,
            model=model,
            extra=merged_extra or None,
            error_code=error_code,
            error_type=error_type,
        )
    elif provider_type in _HF_PROVIDER_TYPES:
        record_registry_metric(
            MetricId.HF_INFERENCE_LATENCY,
            request_id=request_id,
            elapsed_ms=elapsed_ms,
            success=success,
            provider=provider,
            model=model,
            extra=merged_extra or None,
            error_code=error_code,
            error_type=error_type,
        )
