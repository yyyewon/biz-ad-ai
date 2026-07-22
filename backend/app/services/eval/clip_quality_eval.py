"""
생성 완료 후 백그라운드 CLIP 품질 eval.

- CLIP-I: 업로드 원본 vs 생성 이미지 cosine similarity
- CLIP-T: variant 프롬프트 vs 생성 이미지 cosine similarity

결과는 quality.jsonl에 기록한다. API 응답을 블로킹하지 않는다.
"""

from __future__ import annotations

import asyncio
import io
import threading
from typing import Any

from loguru import logger
from PIL import Image

from app.schemas.image_ad import ImageVariantType
from app.schemas.performance_metrics import MetricId
from app.utils.performance_logger import is_performance_logging_enabled, record_registry_metric

CLIP_MODEL_ID = "openai/clip-vit-base-patch32"

_CLIP_MODEL = None
_CLIP_PROCESSOR = None
_CLIP_LOAD_LOCK = threading.RLock()
_CLIP_EVAL_LOCK = threading.Lock()


def is_clip_quality_eval_enabled() -> bool:
    return is_performance_logging_enabled()


def schedule_clip_quality_eval(
    *,
    request_id: str,
    upload_bytes: bytes,
    generated_bytes_list: list[bytes],
    applied_variants: list[ImageVariantType],
    variant_prompts: dict[str, str],
) -> None:
    """
    생성 파이프라인 성공 직후 fire-and-forget CLIP eval task를 등록한다.
    """

    if not is_clip_quality_eval_enabled():
        return

    if not upload_bytes or not generated_bytes_list or not applied_variants:
        return

    snapshot = {
        "request_id": request_id,
        "upload_bytes": bytes(upload_bytes),
        "generated_bytes_list": [bytes(item) for item in generated_bytes_list],
        "applied_variants": list(applied_variants),
        "variant_prompts": dict(variant_prompts),
    }

    try:
        asyncio.get_running_loop().create_task(run_clip_quality_eval(**snapshot))
    except Exception as exc:
        logger.warning(
            "clip_quality_eval_schedule_failed | request_id={} | error={}",
            request_id,
            str(exc),
        )


async def run_clip_quality_eval(
    *,
    request_id: str,
    upload_bytes: bytes,
    generated_bytes_list: list[bytes],
    applied_variants: list[ImageVariantType],
    variant_prompts: dict[str, str],
) -> None:
    """
    CLIP eval을 thread pool에서 실행하고 quality.jsonl에 기록한다.
    """

    try:
        await asyncio.to_thread(
            _run_clip_quality_eval_sync,
            request_id=request_id,
            upload_bytes=upload_bytes,
            generated_bytes_list=generated_bytes_list,
            applied_variants=applied_variants,
            variant_prompts=variant_prompts,
        )
    except Exception as exc:
        logger.exception(
            "clip_quality_eval_failed | request_id={} | error={}",
            request_id,
            str(exc),
        )


def _run_clip_quality_eval_sync(
    *,
    request_id: str,
    upload_bytes: bytes,
    generated_bytes_list: list[bytes],
    applied_variants: list[ImageVariantType],
    variant_prompts: dict[str, str],
) -> None:
    upload_image = _bytes_to_rgb_image(upload_bytes)

    with _CLIP_EVAL_LOCK:
        for variant, generated_bytes in zip(applied_variants, generated_bytes_list, strict=False):
            generated_image = _bytes_to_rgb_image(generated_bytes)
            prompt = variant_prompts.get(variant, "")

            clip_i_score = compute_clip_image_similarity(upload_image, generated_image)
            record_registry_metric(
                MetricId.CLIP_I_SIMILARITY,
                request_id=request_id,
                success=True,
                provider="hf",
                model=CLIP_MODEL_ID,
                extra={
                    "variant": variant,
                    "score": round(clip_i_score, 6),
                    "eval_run_id": request_id,
                },
            )

            if prompt.strip():
                clip_t_score = compute_clip_text_alignment(prompt, generated_image)
                record_registry_metric(
                    MetricId.CLIP_T_ALIGNMENT,
                    request_id=request_id,
                    success=True,
                    provider="hf",
                    model=CLIP_MODEL_ID,
                    extra={
                        "variant": variant,
                        "score": round(clip_t_score, 6),
                        "eval_run_id": request_id,
                        "prompt_chars": len(prompt),
                    },
                )

    logger.info(
        "clip_quality_eval_completed | request_id={} | variant_count={}",
        request_id,
        len(applied_variants),
    )


def compute_clip_image_similarity(left: Image.Image, right: Image.Image) -> float:
    left_embedding = _embed_image(left)
    right_embedding = _embed_image(right)
    return _cosine_similarity(left_embedding, right_embedding)


def compute_clip_text_alignment(prompt: str, image: Image.Image) -> float:
    text_embedding = _embed_text(prompt)
    image_embedding = _embed_image(image)
    return _cosine_similarity(text_embedding, image_embedding)


def _bytes_to_rgb_image(image_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(image_bytes)).convert("RGB")


def _get_clip_model_and_processor():
    global _CLIP_MODEL, _CLIP_PROCESSOR

    with _CLIP_LOAD_LOCK:
        if _CLIP_MODEL is not None and _CLIP_PROCESSOR is not None:
            return _CLIP_MODEL, _CLIP_PROCESSOR

        from transformers import CLIPModel, CLIPProcessor

        logger.info("clip_quality_eval_loading | model_id={} | device=cpu", CLIP_MODEL_ID)
        processor = CLIPProcessor.from_pretrained(CLIP_MODEL_ID)
        model = CLIPModel.from_pretrained(CLIP_MODEL_ID)
        model.eval()
        model.to("cpu")

        _CLIP_MODEL = model
        _CLIP_PROCESSOR = processor
        logger.info("clip_quality_eval_loaded | model_id={}", CLIP_MODEL_ID)
        return _CLIP_MODEL, _CLIP_PROCESSOR


def _embed_image(image: Image.Image) -> Any:
    import torch

    model, processor = _get_clip_model_and_processor()
    inputs = processor(images=image, return_tensors="pt")

    with torch.inference_mode():
        features = model.get_image_features(pixel_values=inputs["pixel_values"])
        tensor = _coerce_clip_features(features)
        if tensor is None:
            vision_outputs = model.vision_model(pixel_values=inputs["pixel_values"])
            pooled = vision_outputs.pooler_output
            if pooled is None:
                pooled = vision_outputs.last_hidden_state[:, 0, :]
            tensor = model.visual_projection(pooled)

    return _normalize_features(tensor)


def _embed_text(prompt: str) -> Any:
    import torch

    model, processor = _get_clip_model_and_processor()
    inputs = processor(
        text=[prompt],
        return_tensors="pt",
        padding=True,
        truncation=True,
    )

    with torch.inference_mode():
        features = model.get_text_features(
            input_ids=inputs["input_ids"],
            attention_mask=inputs.get("attention_mask"),
        )
        tensor = _coerce_clip_features(features)
        if tensor is None:
            text_outputs = model.text_model(
                input_ids=inputs["input_ids"],
                attention_mask=inputs.get("attention_mask"),
            )
            pooled = text_outputs.pooler_output
            if pooled is None:
                pooled = text_outputs.last_hidden_state[:, 0, :]
            tensor = model.text_projection(pooled)

    return _normalize_features(tensor)


def _coerce_clip_features(features: Any) -> Any | None:
    import torch

    if isinstance(features, torch.Tensor):
        return features

    for attr in ("image_embeds", "text_embeds", "pooler_output"):
        if hasattr(features, attr):
            value = getattr(features, attr)
            if value is not None:
                return value

    return None


def _normalize_features(features: Any) -> Any:
    import torch.nn.functional as F

    return F.normalize(features, dim=-1)


def _cosine_similarity(left: Any, right: Any) -> float:
    import torch

    score = torch.matmul(left, right.T).squeeze()
    return float(score.item())
