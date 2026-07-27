"""Central GPU cache release after ad generation pipelines."""

from __future__ import annotations

import gc
from typing import Any

from loguru import logger


def release_all_generation_gpu_resources(*, reason: str, provider: Any | None = None) -> None:
    """
    Drop every cached GPU model used during ad generation.

    Call once after image generation + optional CLIP eval finish.
    """
    logger.info("generation_gpu_release_all | reason={}", reason)

    if provider is not None:
        release_gpu = getattr(provider, "release_gpu_resources", None)
        if callable(release_gpu):
            try:
                release_gpu()
            except Exception as exc:
                logger.warning("generation_gpu_release_boogu_failed | error={}", str(exc))

    try:
        from app.services.providers.hf_boogu_edit_provider import (
            HFBooguEditImageProvider,
        )

        HFBooguEditImageProvider.release_resident_pipeline()
    except Exception as exc:
        logger.warning("generation_gpu_release_boogu_slot_failed | error={}", str(exc))

    try:
        from app.utils.poster_vlm import release_poster_vlm_gpu

        release_poster_vlm_gpu()
    except Exception as exc:
        logger.warning("generation_gpu_release_vlm_failed | error={}", str(exc))

    try:
        from app.services.providers.food_classifier_provider import (
            food_classifier_provider,
        )

        food_classifier_provider.release_gpu()
    except Exception as exc:
        logger.warning("generation_gpu_release_food_classifier_failed | error={}", str(exc))

    try:
        from app.utils.poster_layout import release_rembg_session

        release_rembg_session()
    except Exception as exc:
        logger.warning("generation_gpu_release_rembg_failed | error={}", str(exc))

    try:
        from app.services.eval.clip_quality_eval import release_clip_quality_eval_gpu

        release_clip_quality_eval_gpu()
    except Exception as exc:
        logger.warning("generation_gpu_release_clip_eval_failed | error={}", str(exc))

    _finalize_cuda_pool()


def _finalize_cuda_pool() -> None:
    gc.collect()
    try:
        import torch

        if not torch.cuda.is_available():
            logger.info("generation_gpu_release_all_done | cuda=unavailable")
            return

        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        ipc_collect = getattr(torch.cuda, "ipc_collect", None)
        if callable(ipc_collect):
            ipc_collect()
        gc.collect()
        torch.cuda.empty_cache()

        free_bytes, total_bytes = torch.cuda.mem_get_info()
        allocated_gb = round(torch.cuda.memory_allocated() / (1024**3), 3)
        reserved_gb = round(torch.cuda.memory_reserved() / (1024**3), 3)
        free_gb = round(free_bytes / (1024**3), 3)
        total_gb = round(total_bytes / (1024**3), 3)
        logger.info(
            "generation_gpu_release_all_done | gpu_allocated_gb={} | gpu_reserved_gb={} | "
            "gpu_free_gb={} | gpu_total_gb={}",
            allocated_gb,
            reserved_gb,
            free_gb,
            total_gb,
        )
    except ImportError:
        logger.info("generation_gpu_release_all_done | torch_unavailable")
