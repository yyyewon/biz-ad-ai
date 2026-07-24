"""Boogu-Image-0.1-Edit (TI2I) provider with optional FP8 transformer weights."""

from __future__ import annotations

import gc
import os
import threading
import time
import uuid
from typing import Any

from loguru import logger
from PIL import Image, ImageOps
from starlette.concurrency import run_in_threadpool

from app.core import error_constants as errors
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.model_config import get_model_settings, get_provider_section
from app.services.providers.base import ImageGenerationProvider, ImageRenderMode
from app.utils.image_bytes import image_bytes_to_pil, pil_image_to_png_bytes
from app.utils.memory_monitor import (
    collect_memory_snapshot,
    ensure_model_load_memory,
    log_model_memory_snapshot,
)
from app.utils.performance_logger import record_performance_metric


try:
    import torch
    from boogu.models.transformers.transformer_boogu import BooguImageTransformer2DModel
    from boogu.pipelines.boogu.pipeline_boogu import BooguImagePipeline

    _BOOGU_IMPORT_ERROR: Exception | None = None
except ImportError as _import_exc:
    torch = None
    BooguImagePipeline = None
    BooguImageTransformer2DModel = None
    _BOOGU_IMPORT_ERROR = _import_exc


_PIPELINE_SLOT: dict[str, Any] = {
    "cache_key": None,
    "pipeline": None,
    "meta": None,
}
_PIPELINE_LOAD_LOCK = threading.RLock()
_PIPELINE_INFERENCE_LOCK = threading.Lock()

DEFAULT_NEGATIVE_INSTRUCTION = (
    "blurry, low quality, distorted, deformed, duplicate food, bad anatomy, "
    "text artifacts, watermark, logo, signature, unreadable text, "
    "oversaturated, plastic texture, fake 3d render, "
    "steam, vapor, smoke on iced drinks, overhead top-down angle change, "
    "changed cup shape, wrong drink layers"
)


def _disable_deepgemm_for_fp8_vlm() -> None:
    """Match Boogu inference.py FP8 VLM loading workaround."""
    os.environ["TRANSFORMERS_DISABLE_DEEPGEMM_LINEAR"] = "1"
    try:
        import transformers.integrations.finegrained_fp8 as fg_fp8
    except ImportError:
        return

    def _raise_import_error(*_args: Any, **_kwargs: Any) -> None:
        raise ImportError("DeepGEMM disabled; forcing Triton finegrained-fp8 fallback.")

    if hasattr(fg_fp8, "deepgemm_fp8_fp4_linear"):
        fg_fp8.deepgemm_fp8_fp4_linear = _raise_import_error
    elif hasattr(fg_fp8, "_load_deepgemm_kernel"):
        fg_fp8._load_deepgemm_kernel = _raise_import_error


class HFBooguEditImageProvider(ImageGenerationProvider):
    """Run Boogu-Image-0.1-Edit TI2I with a single reference image."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        model_settings: dict[str, Any] | None = None,
        hf_token: str | None = None,
    ) -> None:
        resolved = get_model_settings(
            role="image_generation",
            provider_name="hf",
            model_name=model_name,
        )
        self._settings = model_settings or resolved["settings"]
        self._model_key = str(resolved["model_name"])
        self._model_id = str(
            self._settings.get("model_id") or "Boogu/Boogu-Image-0.1-Edit-fp8"
        )

        self._device_setting = str(self._settings.get("device", "auto"))
        self._dtype_setting = str(self._settings.get("dtype", "bf16"))
        self._use_fp8_weights = bool(self._settings.get("use_fp8_weights", True))

        self._width = int(self._settings.get("width", 1024))
        self._height = int(self._settings.get("height", 1024))
        self._num_inference_steps = int(self._settings.get("num_inference_steps", 30))
        self._text_guidance_scale = float(
            self._settings.get("text_guidance_scale", 5.0)
        )
        self._image_guidance_scale = float(
            self._settings.get("image_guidance_scale", 1.0)
        )

        self._max_vlm_input_pil_pixels = int(
            self._settings.get("max_vlm_input_pil_pixels", 384 * 384)
        )
        self._max_vlm_input_pil_side_length = int(
            self._settings.get("max_vlm_input_pil_side_length", 768)
        )
        self._max_sequence_length = int(
            self._settings.get("max_sequence_length", 1280)
        )
        self._truncate_instruction_sequence = bool(
            self._settings.get("truncate_instruction_sequence", False)
        )

        self._max_input_image_pixels = int(
            self._settings.get("max_input_image_pixels", 1024 * 1024)
        )
        self._max_input_image_side_length = int(
            self._settings.get("max_input_image_side_length", 2048)
        )

        self._cpu_offload_enabled = bool(
            self._settings.get("cpu_offload_enabled", False)
        )
        self._enable_sequential_cpu_offload = bool(
            self._settings.get("enable_sequential_cpu_offload", False)
        )
        self._low_cpu_mem_usage = bool(
            self._settings.get("low_cpu_mem_usage", True)
        )
        self._min_available_ram_gb = float(
            self._settings.get("min_available_ram_gb", 2.0)
        )

        self._hf_token = hf_token if hf_token is not None else self._resolve_hf_token()

    @staticmethod
    def _resolve_hf_token() -> str:
        hf_config = get_provider_section("hf")
        token_env = str(hf_config.get("token_env", "HF_TOKEN"))
        env_token = os.environ.get(token_env)
        if env_token is not None:
            return env_token.strip()
        return (get_settings().hf_token or "").strip()

    def _ensure_dependencies_available(self) -> None:
        if _BOOGU_IMPORT_ERROR is None:
            return
        raise AppException(
            errors.HF_IMAGE_PIPELINE_DEPENDENCY_ERROR,
            detail={
                "provider": "hf",
                "role": "image_generation",
                "model_name": self._model_key,
                "reason": "boogu-image dependencies import failed",
                "hint": (
                    "Install boogu-image (git --no-deps) and requirements.in Boogu runtime deps."
                ),
                "error": str(_BOOGU_IMPORT_ERROR),
            },
        )

    def _resolve_device(self) -> str:
        self._ensure_dependencies_available()
        configured = self._device_setting.lower()
        if configured != "auto":
            return configured
        if torch.cuda.is_available():
            return "cuda"
        mps_backend = getattr(torch.backends, "mps", None)
        if mps_backend is not None and mps_backend.is_available():
            return "mps"
        return "cpu"

    def _resolve_torch_dtype(self, device: str) -> Any:
        self._ensure_dependencies_available()
        mapping = {
            "fp16": torch.float16,
            "float16": torch.float16,
            "bf16": torch.bfloat16,
            "bfloat16": torch.bfloat16,
            "fp32": torch.float32,
            "float32": torch.float32,
        }
        if self._dtype_setting.lower() == "auto":
            return torch.bfloat16 if device == "cuda" else torch.float32
        dtype = mapping.get(self._dtype_setting.lower(), torch.bfloat16)
        if device == "cpu" and dtype in (torch.float16, torch.bfloat16):
            logger.warning("hf_boogu_cpu_low_precision_fallback | effective_dtype=float32")
            return torch.float32
        return dtype

    @staticmethod
    def _memory_stats() -> dict[str, float | None]:
        return collect_memory_snapshot(torch_module=torch)

    @staticmethod
    def _parse_requested_size(
        size: str | None,
        *,
        default_width: int,
        default_height: int,
    ) -> tuple[int, int]:
        if not size:
            return default_width, default_height
        normalized = size.lower().replace(" ", "")
        if "x" not in normalized:
            return default_width, default_height
        try:
            width_text, height_text = normalized.split("x", 1)
            width, height = int(width_text), int(height_text)
        except (TypeError, ValueError):
            return default_width, default_height
        if width <= 0 or height <= 0:
            return default_width, default_height
        return width, height

    @classmethod
    def _evict_resident_pipeline(cls) -> None:
        pipeline = _PIPELINE_SLOT.get("pipeline")
        _PIPELINE_SLOT.update({"cache_key": None, "pipeline": None, "meta": None})
        if pipeline is None:
            return
        logger.info("hf_boogu_pipeline_evicting | model_key={}", "boogu_edit")
        del pipeline
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("hf_boogu_pipeline_evicted")

    @classmethod
    def release_resident_pipeline(cls) -> None:
        """Drop cached Boogu weights from GPU (e.g. before poster VLM overlay)."""
        cls._evict_resident_pipeline()

    def release_gpu_resources(self) -> None:
        self.release_resident_pipeline()

    def _resolve_local_pipeline_path(self) -> str:
        """
        Boogu custom pipeline은 Hub repo id 직접 로드 시 diffusers가
        model_index.json custom .py 경로를 찾지 못할 수 있다.
        snapshot_download 로컬 디렉터리에서 로드한다 (Boogu inference.py 와 동일).
        """
        from huggingface_hub import snapshot_download

        local_path = snapshot_download(
            repo_id=self._model_id,
            token=self._hf_token or None,
        )
        logger.info(
            "hf_boogu_edit_local_snapshot | model_id={} | local_path={}",
            self._model_id,
            local_path,
        )
        return local_path

    def _load_fp8_transformer(self, *, local_pipeline_path: str, dtype: Any) -> Any:
        assert BooguImageTransformer2DModel is not None
        if "fp8" not in self._model_id.lower():
            raise AppException(
                errors.HF_IMAGE_MODEL_LOAD_FAILED,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "provider_type": "boogu_edit",
                    "model_id": self._model_id,
                    "reason": "use_fp8_weights_requires_fp8_model_id",
                },
            )
        _disable_deepgemm_for_fp8_vlm()
        fp8_transformer_path = os.path.join(local_pipeline_path, "transformer")
        return BooguImageTransformer2DModel.from_pretrained(
            fp8_transformer_path,
            torch_dtype=dtype,
            use_safetensors=False,
            low_cpu_mem_usage=self._low_cpu_mem_usage,
        )

    def _configure_pipeline(self, pipe: Any, *, device: str) -> dict[str, Any]:
        cpu_offload_enabled = False
        sequential_offload_enabled = False

        if device == "cuda" and self._enable_sequential_cpu_offload:
            pipe.enable_sequential_cpu_offload_flag = True
            pipe.enable_sequential_cpu_offload(device=device)
            sequential_offload_enabled = True
        elif device == "cuda" and self._cpu_offload_enabled:
            pipe.enable_model_cpu_offload_flag = True
            pipe.enable_model_cpu_offload(device=device)
            cpu_offload_enabled = True
        else:
            pipe.to(device)

        if hasattr(pipe, "user_set_pipe_device"):
            pipe.user_set_pipe_device = device

        return {
            "cpu_offload_enabled": cpu_offload_enabled,
            "sequential_offload_enabled": sequential_offload_enabled,
            "device": device,
        }

    def _load_pipeline(self) -> tuple[Any, dict[str, Any]]:
        self._ensure_dependencies_available()
        assert BooguImagePipeline is not None

        device = self._resolve_device()
        dtype = self._resolve_torch_dtype(device)
        cache_key = (
            self._model_id,
            self._use_fp8_weights,
            str(dtype),
            device,
            self._cpu_offload_enabled,
            self._enable_sequential_cpu_offload,
        )

        if _PIPELINE_SLOT.get("cache_key") == cache_key:
            return _PIPELINE_SLOT["pipeline"], _PIPELINE_SLOT["meta"]

        with _PIPELINE_LOAD_LOCK:
            if _PIPELINE_SLOT.get("cache_key") == cache_key:
                return _PIPELINE_SLOT["pipeline"], _PIPELINE_SLOT["meta"]

            request_id = f"hf-boogu-load-{uuid.uuid4().hex[:10]}"
            started = time.perf_counter()
            load_stage = "before_boogu_edit_pipeline_load"
            before_load = log_model_memory_snapshot(
                load_stage,
                model_name=self._model_key,
                torch_module=torch,
            )
            ensure_model_load_memory(
                model_name=self._model_key,
                min_available_ram_gb=self._min_available_ram_gb,
                load_stage=load_stage,
                snapshot=before_load,
            )

            self._evict_resident_pipeline()
            pipe: Any | None = None

            try:
                _disable_deepgemm_for_fp8_vlm()
                logger.info(
                    "hf_boogu_edit_pipeline_loading | model_key={} | model_id={} | "
                    "device={} | dtype={} | use_fp8_weights={}",
                    self._model_key,
                    self._model_id,
                    device,
                    str(dtype),
                    self._use_fp8_weights,
                )

                load_kwargs: dict[str, Any] = {
                    "torch_dtype": dtype,
                    "trust_remote_code": True,
                    "low_cpu_mem_usage": self._low_cpu_mem_usage,
                }
                local_pipeline_path = self._resolve_local_pipeline_path()
                if self._use_fp8_weights:
                    fp8_transformer = self._load_fp8_transformer(
                        local_pipeline_path=local_pipeline_path,
                        dtype=dtype,
                    )
                    pipe = BooguImagePipeline.from_pretrained(
                        local_pipeline_path,
                        transformer=fp8_transformer,
                        **load_kwargs,
                    )
                else:
                    pipe = BooguImagePipeline.from_pretrained(
                        local_pipeline_path,
                        **load_kwargs,
                    )

                meta = self._configure_pipeline(pipe, device=device)
                elapsed_ms = (time.perf_counter() - started) * 1000
                memory = self._memory_stats()

                _PIPELINE_SLOT.update(
                    {
                        "cache_key": cache_key,
                        "pipeline": pipe,
                        "meta": meta,
                    }
                )

                record_performance_metric(
                    pipeline="hf_boogu_edit",
                    stage="model_load",
                    request_id=request_id,
                    provider="hf",
                    model=self._model_key,
                    elapsed_ms=elapsed_ms,
                    success=True,
                    extra={
                        "provider_type": "boogu_edit",
                        "model_id": self._model_id,
                        "use_fp8_weights": self._use_fp8_weights,
                        **meta,
                        **memory,
                    },
                )
                logger.info(
                    "hf_boogu_edit_pipeline_loaded | model_key={} | model_id={} | "
                    "device={} | elapsed_ms={:.2f}",
                    self._model_key,
                    self._model_id,
                    device,
                    elapsed_ms,
                )
                return pipe, meta

            except AppException:
                raise
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - started) * 1000
                record_performance_metric(
                    pipeline="hf_boogu_edit",
                    stage="model_load",
                    request_id=request_id,
                    provider="hf",
                    model=self._model_key,
                    elapsed_ms=elapsed_ms,
                    success=False,
                    error_code="HF_BOOGU_EDIT_MODEL_LOAD_FAILED",
                    error_type=exc.__class__.__name__,
                    extra={
                        "provider_type": "boogu_edit",
                        "model_id": self._model_id,
                    },
                )
                raise AppException(
                    errors.HF_IMAGE_MODEL_LOAD_FAILED,
                    detail={
                        "provider": "hf",
                        "role": "image_generation",
                        "provider_type": "boogu_edit",
                        "model_name": self._model_key,
                        "model_id": self._model_id,
                        "error": str(exc),
                    },
                ) from exc

    @staticmethod
    def _normalize_output_images(raw: Any) -> list[Image.Image]:
        if raw is None:
            return []
        if isinstance(raw, Image.Image):
            return [raw.convert("RGB")]
        if isinstance(raw, list):
            return [item.convert("RGB") for item in raw if isinstance(item, Image.Image)]
        images = getattr(raw, "images", None)
        if images is not None:
            return HFBooguEditImageProvider._normalize_output_images(images)
        return []

    async def generate_backgrounds(
        self,
        *,
        prompt: str,
        num_images: int,
    ) -> list[bytes]:
        _ = (prompt, num_images)
        raise AppException(
            errors.IMAGE_INPUT_FILE_NOT_FOUND,
            detail={
                "provider": "hf",
                "role": "image_generation",
                "provider_type": "boogu_edit",
                "reason": "boogu_edit_requires_input_image",
            },
        )

    async def generate(
        self,
        *,
        input_image_bytes: bytes,
        prompt: str,
        num_images: int,
        mask_image_bytes: bytes | None = None,
        size: str | None = None,
        render_mode: ImageRenderMode = "photo_restyle",
        negative_prompt: str | None = None,
        img2img_strength: float | None = None,
    ) -> list[bytes]:
        _ = (mask_image_bytes, img2img_strength)
        return await run_in_threadpool(
            self._generate_sync,
            input_image_bytes=input_image_bytes,
            prompt=prompt,
            num_images=num_images,
            size=size,
            render_mode=render_mode,
            negative_prompt=negative_prompt,
        )

    def _generate_sync(
        self,
        *,
        input_image_bytes: bytes,
        prompt: str,
        num_images: int,
        size: str | None,
        render_mode: ImageRenderMode,
        negative_prompt: str | None,
    ) -> list[bytes]:
        if not input_image_bytes:
            raise AppException(
                errors.IMAGE_INPUT_FILE_NOT_FOUND,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "provider_type": "boogu_edit",
                    "reason": "input_image_bytes_empty",
                },
            )

        instruction = prompt.strip()
        if not instruction:
            raise AppException(
                errors.HF_IMAGE_GENERATION_FAILED,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "provider_type": "boogu_edit",
                    "reason": "instruction_empty",
                },
            )

        if render_mode != "photo_restyle":
            raise ValueError(f"Unsupported render_mode for boogu_edit: {render_mode}")

        width, height = self._parse_requested_size(
            size,
            default_width=self._width,
            default_height=self._height,
        )
        effective_num_images = max(1, int(num_images or 1))
        device = self._resolve_device()
        request_id = f"hf-boogu-gen-{uuid.uuid4().hex[:10]}"
        started = time.perf_counter()

        reference_image = ImageOps.exif_transpose(
            image_bytes_to_pil(input_image_bytes).convert("RGB")
        )

        logger.info(
            "hf_boogu_edit_generation_started | model_key={} | width={} | height={} | "
            "num_images={} | instruction_chars={}",
            self._model_key,
            width,
            height,
            effective_num_images,
            len(instruction),
        )

        try:
            with _PIPELINE_INFERENCE_LOCK:
                pipe, load_meta = self._load_pipeline()
                generator = None
                if device.startswith("cuda") and torch is not None:
                    generator = torch.Generator(device=device)

                result = pipe(
                    instruction=instruction,
                    negative_instruction=negative_prompt or DEFAULT_NEGATIVE_INSTRUCTION,
                    input_images=[[reference_image]],
                    width=width,
                    height=height,
                    max_input_image_pixels=self._max_input_image_pixels,
                    max_input_image_side_length=self._max_input_image_side_length,
                    max_vlm_input_pil_pixels=self._max_vlm_input_pil_pixels,
                    max_vlm_input_pil_side_length=self._max_vlm_input_pil_side_length,
                    max_sequence_length=self._max_sequence_length,
                    truncate_instruction_sequence=self._truncate_instruction_sequence,
                    num_inference_steps=self._num_inference_steps,
                    text_guidance_scale=self._text_guidance_scale,
                    image_guidance_scale=self._image_guidance_scale,
                    num_images_per_instruction=effective_num_images,
                    generator=generator,
                    output_type="pil",
                    device=device,
                )

                if torch is not None and torch.cuda.is_available():
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()

            images = self._normalize_output_images(result)
            if not images:
                raise AppException(
                    errors.IMAGE_GENERATION_EMPTY_RESULT,
                    detail={
                        "provider": "hf",
                        "role": "image_generation",
                        "provider_type": "boogu_edit",
                        "model_name": self._model_key,
                    },
                )

            output_bytes = [
                pil_image_to_png_bytes(image.resize((width, height)))
                for image in images[:effective_num_images]
            ]

            elapsed_ms = (time.perf_counter() - started) * 1000
            memory = self._memory_stats()
            record_performance_metric(
                pipeline="hf_boogu_edit",
                stage="inference",
                request_id=request_id,
                provider="hf",
                model=self._model_key,
                elapsed_ms=elapsed_ms,
                success=True,
                extra={
                    "provider_type": "boogu_edit",
                    "model_id": self._model_id,
                    "width": width,
                    "height": height,
                    "num_images": len(output_bytes),
                    "num_inference_steps": self._num_inference_steps,
                    "text_guidance_scale": self._text_guidance_scale,
                    **load_meta,
                    **memory,
                },
            )
            logger.info(
                "hf_boogu_edit_generation_completed | model_key={} | generated_count={} | "
                "elapsed_ms={:.2f}",
                self._model_key,
                len(output_bytes),
                elapsed_ms,
            )
            return output_bytes

        except AppException:
            raise
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            record_performance_metric(
                pipeline="hf_boogu_edit",
                stage="inference",
                request_id=request_id,
                provider="hf",
                model=self._model_key,
                elapsed_ms=elapsed_ms,
                success=False,
                error_code="HF_BOOGU_EDIT_GENERATION_FAILED",
                error_type=exc.__class__.__name__,
                extra={
                    "provider_type": "boogu_edit",
                    "model_id": self._model_id,
                    "width": width,
                    "height": height,
                },
            )
            logger.exception(
                "hf_boogu_edit_generation_failed | model_key={} | error={}",
                self._model_key,
                str(exc),
            )
            raise AppException(
                errors.HF_IMAGE_GENERATION_FAILED,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "provider_type": "boogu_edit",
                    "model_name": self._model_key,
                    "error": str(exc),
                },
            ) from exc
