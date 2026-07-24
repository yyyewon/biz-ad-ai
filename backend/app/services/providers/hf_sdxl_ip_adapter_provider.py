"""SDXL img2img/inpaint provider with IP-Adapter Plus image conditioning."""

from __future__ import annotations

import gc
import math
import os
import threading
import time
import uuid
from typing import Any, Literal

from loguru import logger
from PIL import Image, ImageOps
from starlette.concurrency import run_in_threadpool

from app.core import error_constants as errors
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.model_config import get_provider_section
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
    from diffusers import (
        StableDiffusionXLImg2ImgPipeline,
        StableDiffusionXLInpaintPipeline,
    )

    _SDXL_IMPORT_ERROR: Exception | None = None
except ImportError as _import_exc:
    torch = None
    StableDiffusionXLImg2ImgPipeline = None
    StableDiffusionXLInpaintPipeline = None
    _SDXL_IMPORT_ERROR = _import_exc


PipelineKind = Literal["img2img", "inpaint"]

# Only one heavy SDXL pipeline may be resident. This is intentionally shared by
# all provider instances because service variants are generated concurrently.
_PIPELINE_SLOT: dict[str, Any] = {
    "kind": None,
    "cache_key": None,
    "pipeline": None,
    "meta": None,
}
_PIPELINE_LOAD_LOCK = threading.RLock()
_PIPELINE_INFERENCE_LOCK = threading.Lock()


DEFAULT_NEGATIVE_PROMPT = (
    "blurry, low quality, distorted, deformed, duplicate food, bad anatomy, "
    "text artifacts, watermark, logo, signature, unreadable text, "
    "oversaturated, plastic texture, fake 3d render"
)


class HFSDXLIPAdapterImageProvider(ImageGenerationProvider):
    """Run SDXL img2img or inpaint with the same IP-Adapter Plus reference."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        model_settings: dict[str, Any] | None = None,
        hf_token: str | None = None,
    ) -> None:
        self._settings = model_settings or {}
        self._model_key = str(model_name or "sdxl_ip_adapter")
        self._base_model_id = str(
            self._settings.get("base_model_id")
            or "stabilityai/stable-diffusion-xl-base-1.0"
        )
        self._inpaint_model_id = str(
            self._settings.get("inpaint_model_id")
            or "diffusers/stable-diffusion-xl-1.0-inpainting-0.1"
        )

        ip_adapter = self._settings.get("ip_adapter")
        if not isinstance(ip_adapter, dict):
            ip_adapter = {}
        self._ip_adapter_enabled = bool(ip_adapter.get("enabled", True))
        self._ip_adapter_repo_id = str(ip_adapter.get("repo_id") or "h94/IP-Adapter")
        self._ip_adapter_subfolder = str(
            ip_adapter.get("subfolder") or "sdxl_models"
        )
        self._ip_adapter_weight_name = str(
            ip_adapter.get("weight_name")
            or "ip-adapter-plus_sdxl_vit-h.safetensors"
        )
        self._ip_adapter_image_encoder_folder = str(
            ip_adapter.get("image_encoder_folder") or "models/image_encoder"
        )
        self._ip_adapter_scale = float(
            ip_adapter.get("scale", self._settings.get("ip_adapter_scale", 0.55))
        )

        self._device_setting = str(self._settings.get("device", "auto"))
        self._dtype_setting = str(self._settings.get("dtype", "fp16"))
        self._width = int(self._settings.get("width", 1024))
        self._height = int(self._settings.get("height", 1024))
        self._max_native_side = int(
            self._settings.get(
                "max_native_side",
                round(max(self._width, self._height) * 1.125),
            )
        )
        self._num_inference_steps = int(
            self._settings.get("num_inference_steps", 25)
        )
        self._guidance_scale = float(self._settings.get("guidance_scale", 5.5))
        self._img2img_restyle_strength = float(
            self._settings.get("img2img_restyle_strength", 0.35)
        )
        self._inpaint_strength = float(self._settings.get("inpaint_strength", 0.90))
        self._num_images_per_prompt = int(
            self._settings.get("num_images_per_prompt", 1)
        )

        self._use_safetensors = bool(self._settings.get("use_safetensors", True))
        self._low_cpu_mem_usage = bool(
            self._settings.get("low_cpu_mem_usage", True)
        )
        self._enable_vae_slicing = bool(
            self._settings.get("enable_vae_slicing", True)
        )
        self._enable_vae_tiling = bool(
            self._settings.get("enable_vae_tiling", False)
        )
        self._use_xformers = bool(self._settings.get("use_xformers", False))
        self._max_resident_pipelines = int(
            self._settings.get("max_resident_pipelines", 1)
        )

        runtime_settings = get_settings()
        self._cpu_offload_enabled = bool(
            self._settings.get(
                "cpu_offload_enabled",
                runtime_settings.hf_image_cpu_offload_enabled,
            )
        )
        self._min_available_ram_gb = (
            runtime_settings.model_load_min_available_ram_gb
        )
        self._hf_token = hf_token or self._resolve_hf_token()

        if self._max_resident_pipelines != 1:
            logger.warning(
                "hf_sdxl_pipeline_cache_clamped | requested={} | effective=1",
                self._max_resident_pipelines,
            )
            self._max_resident_pipelines = 1

        if not 0.0 < self._ip_adapter_scale <= 1.0:
            raise ValueError("ip_adapter scale must be in the range (0, 1]")
        if self._num_images_per_prompt != 1:
            logger.warning(
                "hf_sdxl_batch_size_clamped | requested={} | effective=1",
                self._num_images_per_prompt,
            )
            self._num_images_per_prompt = 1
        if not self._hf_token:
            raise AppException(
                errors.HF_TOKEN_MISSING,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "model_name": self._model_key,
                    "reason": "hf_token_missing",
                },
            )

    @property
    def model_id(self) -> str:
        return self._base_model_id

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @staticmethod
    def _resolve_hf_token() -> str:
        hf_config = get_provider_section("hf")
        token_env = str(hf_config.get("token_env", "HF_TOKEN"))
        env_token = os.environ.get(token_env)
        if env_token is not None:
            return env_token.strip()
        return (get_settings().hf_token or "").strip()

    def _ensure_dependencies_available(self) -> None:
        if _SDXL_IMPORT_ERROR is None:
            return
        raise AppException(
            errors.HF_IMAGE_PIPELINE_DEPENDENCY_ERROR,
            detail={
                "provider": "hf",
                "role": "image_generation",
                "model_name": self._model_key,
                "reason": "sdxl ip-adapter dependencies import failed",
                "error": str(_SDXL_IMPORT_ERROR),
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
            return torch.float16 if device == "cuda" else torch.float32
        dtype = mapping.get(self._dtype_setting.lower(), torch.float16)
        if device == "cpu" and dtype == torch.float16:
            logger.warning("hf_sdxl_cpu_fp16_fallback | effective_dtype=float32")
            return torch.float32
        return dtype

    @staticmethod
    def _memory_stats() -> dict[str, float | None]:
        return collect_memory_snapshot(torch_module=torch)

    @staticmethod
    def _align(value: float, *, multiple: int = 64, minimum: int = 512) -> int:
        return max(minimum, int(round(value / multiple)) * multiple)

    def _parse_requested_size(self, size: str | None) -> tuple[int, int]:
        if not size:
            return self._width, self._height
        normalized = size.lower().replace(" ", "")
        if "x" not in normalized:
            return self._width, self._height
        try:
            width_text, height_text = normalized.split("x", 1)
            width, height = int(width_text), int(height_text)
        except (TypeError, ValueError):
            return self._width, self._height
        if width <= 0 or height <= 0:
            return self._width, self._height
        return width, height

    def _resolve_native_size(self, requested: tuple[int, int]) -> tuple[int, int]:
        """Choose an SDXL-safe aspect bucket without using the large API size."""
        requested_width, requested_height = requested
        ratio = requested_width / requested_height
        max_pixels = max(512 * 512, self._width * self._height)
        ideal_height = math.sqrt(max_pixels / ratio)
        ideal_width = ideal_height * ratio
        longest = max(ideal_width, ideal_height)
        if longest > self._max_native_side:
            scale = self._max_native_side / longest
            ideal_width *= scale
            ideal_height *= scale

        width = min(self._max_native_side, self._align(ideal_width))
        height = min(self._max_native_side, self._align(ideal_height))
        while width * height > max_pixels:
            if width >= height and width > 512:
                width -= 64
            elif height > 512:
                height -= 64
            else:
                break
        return width, height

    @staticmethod
    def _fit_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
        return ImageOps.fit(
            image.convert("RGB"),
            size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

    @staticmethod
    def _fit_mask(
        mask: Image.Image,
        *,
        source_size: tuple[int, int],
        target_size: tuple[int, int],
    ) -> Image.Image:
        if mask.size != source_size:
            mask = mask.resize(source_size, Image.Resampling.NEAREST)
        return ImageOps.fit(
            mask.convert("L"),
            target_size,
            method=Image.Resampling.NEAREST,
            centering=(0.5, 0.5),
        )

    @staticmethod
    def _explicit_inpaint_mask(mask_image: Image.Image) -> Image.Image:
        """Convert subject-alpha masks to Diffusers' white=repaint convention."""
        if "A" in mask_image.getbands():
            alpha = mask_image.getchannel("A")
            if alpha.getextrema() != (255, 255):
                return ImageOps.invert(alpha)
        return mask_image.convert("L")

    def _build_inpaint_mask(
        self,
        *,
        source_rgba: Image.Image,
        mask_image_bytes: bytes | None,
    ) -> Image.Image:
        if mask_image_bytes:
            mask_image = image_bytes_to_pil(mask_image_bytes)
            return self._explicit_inpaint_mask(mask_image)

        source_alpha = source_rgba.getchannel("A")
        if source_alpha.getextrema() != (255, 255):
            return ImageOps.invert(source_alpha)

        logger.warning(
            "hf_sdxl_background_swap_without_alpha | fallback=full_image_inpaint"
        )
        return Image.new("L", source_rgba.size, 255)

    @staticmethod
    def _is_cuda_oom(exc: Exception) -> bool:
        oom_type = getattr(getattr(torch, "cuda", None), "OutOfMemoryError", None)
        return (oom_type is not None and isinstance(exc, oom_type)) or (
            "cuda" in str(exc).lower() and "out of memory" in str(exc).lower()
        )

    @classmethod
    def _evict_resident_pipeline(cls) -> None:
        pipeline = _PIPELINE_SLOT.get("pipeline")
        evicted_kind = _PIPELINE_SLOT.get("kind")
        _PIPELINE_SLOT.update(
            {"kind": None, "cache_key": None, "pipeline": None, "meta": None}
        )
        if pipeline is None:
            return
        logger.info("hf_sdxl_pipeline_evicting | pipeline_kind={}", evicted_kind)
        del pipeline
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("hf_sdxl_pipeline_evicted | pipeline_kind={}", evicted_kind)

    def _configure_pipeline(self, pipe: Any, *, device: str) -> dict[str, Any]:
        if self._enable_vae_slicing:
            try:
                pipe.vae.enable_slicing()
            except Exception as exc:
                logger.warning("hf_sdxl_vae_slicing_failed | error={}", str(exc))
        if self._enable_vae_tiling:
            try:
                pipe.vae.enable_tiling()
            except Exception as exc:
                logger.warning("hf_sdxl_vae_tiling_failed | error={}", str(exc))

        xformers_enabled = False
        xformers_error = None
        if self._use_xformers:
            try:
                pipe.enable_xformers_memory_efficient_attention()
                xformers_enabled = True
            except Exception as exc:
                xformers_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "hf_sdxl_xformers_enable_failed | fallback=sdpa | error={}",
                    xformers_error,
                )

        cpu_offload_enabled = self._cpu_offload_enabled and device == "cuda"
        if cpu_offload_enabled:
            pipe.enable_model_cpu_offload()
        else:
            pipe.to(device)
        return {
            "cpu_offload_enabled": cpu_offload_enabled,
            "xformers_enabled": xformers_enabled,
            "xformers_error": xformers_error,
            "attention_backend": "xformers" if xformers_enabled else "sdpa",
        }

    def _load_pipeline(self, pipeline_kind: PipelineKind) -> tuple[Any, dict[str, Any]]:
        self._ensure_dependencies_available()
        device = self._resolve_device()
        dtype = self._resolve_torch_dtype(device)
        model_id = (
            self._base_model_id
            if pipeline_kind == "img2img"
            else self._inpaint_model_id
        )
        cache_key = (
            pipeline_kind,
            model_id,
            self._ip_adapter_repo_id,
            self._ip_adapter_subfolder,
            self._ip_adapter_weight_name,
            self._ip_adapter_scale,
            str(dtype),
            device,
            self._cpu_offload_enabled,
            self._use_xformers,
        )
        if _PIPELINE_SLOT.get("cache_key") == cache_key:
            return _PIPELINE_SLOT["pipeline"], _PIPELINE_SLOT["meta"]

        with _PIPELINE_LOAD_LOCK:
            if _PIPELINE_SLOT.get("cache_key") == cache_key:
                return _PIPELINE_SLOT["pipeline"], _PIPELINE_SLOT["meta"]

            request_id = f"hf-sdxl-load-{uuid.uuid4().hex[:10]}"
            started = time.perf_counter()
            pipe: Any | None = None
            self._evict_resident_pipeline()
            load_stage = f"before_{pipeline_kind}_pipeline_load"
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
                torch_module=torch,
            )

            try:
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.reset_peak_memory_stats()
                pipeline_class = (
                    StableDiffusionXLImg2ImgPipeline
                    if pipeline_kind == "img2img"
                    else StableDiffusionXLInpaintPipeline
                )
                load_kwargs: dict[str, Any] = {
                    "pretrained_model_name_or_path": model_id,
                    "torch_dtype": dtype,
                    "use_safetensors": self._use_safetensors,
                    "low_cpu_mem_usage": self._low_cpu_mem_usage,
                    "token": self._hf_token,
                }
                if dtype == torch.float16:
                    load_kwargs["variant"] = "fp16"
                pipe = pipeline_class.from_pretrained(**load_kwargs)

                if self._ip_adapter_enabled:
                    pipe.load_ip_adapter(
                        self._ip_adapter_repo_id,
                        subfolder=self._ip_adapter_subfolder,
                        weight_name=self._ip_adapter_weight_name,
                        image_encoder_folder=self._ip_adapter_image_encoder_folder,
                    )
                    pipe.set_ip_adapter_scale(self._ip_adapter_scale)
                    logger.info(
                        "hf_sdxl_ip_adapter_loaded | pipeline_kind={} | repo_id={} | "
                        "subfolder={} | weight_name={} | scale={}",
                        pipeline_kind,
                        self._ip_adapter_repo_id,
                        self._ip_adapter_subfolder,
                        self._ip_adapter_weight_name,
                        self._ip_adapter_scale,
                    )

                optimization_meta = self._configure_pipeline(pipe, device=device)
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                elapsed_ms = (time.perf_counter() - started) * 1000
                after_load = log_model_memory_snapshot(
                    f"after_{pipeline_kind}_pipeline_load",
                    model_name=self._model_key,
                    torch_module=torch,
                )
                meta: dict[str, Any] = {
                    "provider_type": "sdxl_ip_adapter",
                    "pipeline_kind": pipeline_kind,
                    "model_id": model_id,
                    "device": device,
                    "dtype": str(dtype),
                    "ip_adapter_enabled": self._ip_adapter_enabled,
                    "ip_adapter_repo_id": self._ip_adapter_repo_id,
                    "ip_adapter_weight_name": self._ip_adapter_weight_name,
                    "ip_adapter_scale": self._ip_adapter_scale,
                    "max_resident_pipelines": 1,
                    "memory_before_load": before_load,
                    "memory_after_load": after_load,
                    **optimization_meta,
                }
                _PIPELINE_SLOT.update(
                    {
                        "kind": pipeline_kind,
                        "cache_key": cache_key,
                        "pipeline": pipe,
                        "meta": meta,
                    }
                )
                record_performance_metric(
                    pipeline="hf_sdxl_ip_adapter",
                    stage=f"{pipeline_kind}_model_load",
                    request_id=request_id,
                    provider="hf",
                    model=self._model_key,
                    elapsed_ms=elapsed_ms,
                    success=True,
                    extra=meta,
                )
                logger.info(
                    "hf_sdxl_pipeline_loaded | pipeline_kind={} | model_id={} | "
                    "elapsed_ms={:.2f} | gpu_allocated_gb={} | gpu_reserved_gb={}",
                    pipeline_kind,
                    model_id,
                    elapsed_ms,
                    after_load.get("gpu_memory_allocated_gb"),
                    after_load.get("gpu_memory_reserved_gb"),
                )
                return pipe, meta
            except AppException:
                raise
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - started) * 1000
                pipe = None
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                record_performance_metric(
                    pipeline="hf_sdxl_ip_adapter",
                    stage=f"{pipeline_kind}_model_load",
                    request_id=request_id,
                    provider="hf",
                    model=self._model_key,
                    elapsed_ms=elapsed_ms,
                    success=False,
                    error_code="HF_SDXL_IP_ADAPTER_MODEL_LOAD_FAILED",
                    error_type=exc.__class__.__name__,
                    extra={
                        "provider_type": "sdxl_ip_adapter",
                        "pipeline_kind": pipeline_kind,
                        "model_id": model_id,
                    },
                )
                raise AppException(
                    errors.HF_IMAGE_MODEL_LOAD_FAILED,
                    detail={
                        "provider": "hf",
                        "role": "image_generation",
                        "provider_type": "sdxl_ip_adapter",
                        "pipeline_kind": pipeline_kind,
                        "model_name": self._model_key,
                        "error": str(exc),
                    },
                ) from exc

    @staticmethod
    def _log_prompt_token_count(pipe: Any, prompt: str) -> None:
        for name in ("tokenizer", "tokenizer_2"):
            tokenizer = getattr(pipe, name, None)
            if tokenizer is None:
                continue
            try:
                input_ids = tokenizer(
                    prompt,
                    add_special_tokens=True,
                    truncation=False,
                )["input_ids"]
                token_count = len(input_ids)
                model_max_length = int(getattr(tokenizer, "model_max_length", 0) or 0)
                logger.info(
                    "hf_sdxl_prompt_tokens | tokenizer={} | token_count={} | max_length={}",
                    name,
                    token_count,
                    model_max_length,
                )
                if 0 < model_max_length < 10000 and token_count > model_max_length:
                    logger.warning(
                        "hf_sdxl_prompt_too_long | tokenizer={} | token_count={} | max_length={}",
                        name,
                        token_count,
                        model_max_length,
                    )
            except Exception as exc:
                logger.warning(
                    "hf_sdxl_prompt_token_count_failed | tokenizer={} | error={}",
                    name,
                    str(exc),
                )

    def _resolve_img2img_strength(self, value: float | None) -> float:
        strength = self._img2img_restyle_strength if value is None else float(value)
        if not 0.0 < strength <= 1.0:
            raise ValueError("img2img_strength must be in the range (0, 1]")
        return strength

    @staticmethod
    def _fallback_size(size: tuple[int, int]) -> tuple[int, int] | None:
        width, height = size
        fallback = (
            max(512, int(width * 0.75) // 64 * 64),
            max(512, int(height * 0.75) // 64 * 64),
        )
        return None if fallback == size else fallback

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
                "provider_type": "sdxl_ip_adapter",
                "reason": "sdxl_img2img_requires_input_image",
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
        return await run_in_threadpool(
            self._generate_sync,
            input_image_bytes=input_image_bytes,
            prompt=prompt,
            num_images=num_images,
            mask_image_bytes=mask_image_bytes,
            size=size,
            render_mode=render_mode,
            negative_prompt=negative_prompt,
            img2img_strength=img2img_strength,
        )

    def _generate_sync(
        self,
        *,
        input_image_bytes: bytes,
        prompt: str,
        num_images: int,
        mask_image_bytes: bytes | None,
        size: str | None,
        render_mode: ImageRenderMode,
        negative_prompt: str | None,
        img2img_strength: float | None,
    ) -> list[bytes]:
        if not input_image_bytes:
            raise AppException(
                errors.IMAGE_INPUT_FILE_NOT_FOUND,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "provider_type": "sdxl_ip_adapter",
                    "reason": "input_image_bytes_empty",
                },
            )
        prompt = prompt.strip()
        if not prompt:
            raise AppException(
                errors.HF_IMAGE_GENERATION_FAILED,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "provider_type": "sdxl_ip_adapter",
                    "reason": "prompt_empty",
                },
            )
        if render_mode not in ("photo_restyle", "background_swap"):
            raise ValueError(f"Unsupported render_mode: {render_mode}")

        source_rgba = image_bytes_to_pil(input_image_bytes).convert("RGBA")
        mask = None
        pipeline_kind: PipelineKind = "img2img"
        strength = self._resolve_img2img_strength(img2img_strength)
        if mask_image_bytes is not None or render_mode == "background_swap":
            pipeline_kind = "inpaint"
            strength = self._inpaint_strength
            mask = self._build_inpaint_mask(
                source_rgba=source_rgba,
                mask_image_bytes=mask_image_bytes,
            )

        return self._generate_images_sync(
            source_rgba=source_rgba,
            mask=mask,
            pipeline_kind=pipeline_kind,
            prompt=prompt,
            negative_prompt=negative_prompt or DEFAULT_NEGATIVE_PROMPT,
            num_images=num_images,
            requested_size=self._parse_requested_size(size),
            strength=strength,
        )

    def _generate_images_sync(
        self,
        *,
        source_rgba: Image.Image,
        mask: Image.Image | None,
        pipeline_kind: PipelineKind,
        prompt: str,
        negative_prompt: str,
        num_images: int,
        requested_size: tuple[int, int],
        strength: float,
    ) -> list[bytes]:
        request_id = f"hf-sdxl-gen-{uuid.uuid4().hex[:10]}"
        native_size = self._resolve_native_size(requested_size)
        effective_num_images = max(1, int(num_images or 1))
        started = time.perf_counter()
        load_meta: dict[str, Any] = {}
        used_native_size = native_size
        fallback_used = False

        try:
            with _PIPELINE_INFERENCE_LOCK:
                pipe, load_meta = self._load_pipeline(pipeline_kind)
                self._log_prompt_token_count(pipe, prompt)
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.reset_peak_memory_stats()

                output_images: list[bytes] = []
                for image_index in range(effective_num_images):
                    attempt_sizes = [native_size]
                    fallback_size = self._fallback_size(native_size)
                    if fallback_size is not None:
                        attempt_sizes.append(fallback_size)

                    for attempt_index, attempt_size in enumerate(attempt_sizes):
                        prepared_image = self._fit_image(source_rgba, attempt_size)
                        kwargs: dict[str, Any] = {
                            "prompt": prompt,
                            "negative_prompt": negative_prompt,
                            "image": prepared_image,
                            "strength": strength,
                            "num_inference_steps": self._num_inference_steps,
                            "guidance_scale": self._guidance_scale,
                            "num_images_per_prompt": 1,
                        }
                        if self._ip_adapter_enabled:
                            kwargs["ip_adapter_image"] = prepared_image
                        if pipeline_kind == "inpaint":
                            if mask is None:
                                raise ValueError("inpaint pipeline requires a mask")
                            kwargs.update(
                                {
                                    "mask_image": self._fit_mask(
                                        mask,
                                        source_size=source_rgba.size,
                                        target_size=attempt_size,
                                    ),
                                    "width": attempt_size[0],
                                    "height": attempt_size[1],
                                }
                            )

                        logger.info(
                            "hf_sdxl_generation_started | pipeline_kind={} | image_index={} | "
                            "requested_size={}x{} | native_size={}x{} | strength={} | steps={} | "
                            "guidance_scale={} | ip_adapter_scale={}",
                            pipeline_kind,
                            image_index,
                            requested_size[0],
                            requested_size[1],
                            attempt_size[0],
                            attempt_size[1],
                            strength,
                            self._num_inference_steps,
                            self._guidance_scale,
                            self._ip_adapter_scale,
                        )
                        try:
                            result = pipe(**kwargs)
                        except Exception as exc:
                            can_retry = (
                                attempt_index == 0
                                and len(attempt_sizes) == 2
                                and self._is_cuda_oom(exc)
                            )
                            if not can_retry:
                                raise
                            fallback_used = True
                            logger.warning(
                                "hf_sdxl_cuda_oom_fallback | pipeline_kind={} | "
                                "from_size={}x{} | to_size={}x{}",
                                pipeline_kind,
                                attempt_size[0],
                                attempt_size[1],
                                attempt_sizes[1][0],
                                attempt_sizes[1][1],
                            )
                            gc.collect()
                            torch.cuda.empty_cache()
                            continue

                        images = list(getattr(result, "images", []) or [])
                        if not images:
                            raise AppException(
                                errors.IMAGE_GENERATION_EMPTY_RESULT,
                                detail={
                                    "provider": "hf",
                                    "role": "image_generation",
                                    "provider_type": "sdxl_ip_adapter",
                                    "pipeline_kind": pipeline_kind,
                                    "model_name": self._model_key,
                                },
                            )
                        used_native_size = attempt_size
                        final_image = ImageOps.fit(
                            images[0].convert("RGB"),
                            requested_size,
                            method=Image.Resampling.LANCZOS,
                            centering=(0.5, 0.5),
                        )
                        output_images.append(pil_image_to_png_bytes(final_image))
                        break

                if torch.cuda.is_available():
                    torch.cuda.synchronize()

            elapsed_ms = (time.perf_counter() - started) * 1000
            memory = self._memory_stats()
            extra = {
                **load_meta,
                **memory,
                "pipeline_kind": pipeline_kind,
                "requested_width": requested_size[0],
                "requested_height": requested_size[1],
                "native_width": used_native_size[0],
                "native_height": used_native_size[1],
                "num_images": len(output_images),
                "num_inference_steps": self._num_inference_steps,
                "guidance_scale": self._guidance_scale,
                "strength": strength,
                "ip_adapter_scale": self._ip_adapter_scale,
                "oom_fallback_used": fallback_used,
            }
            record_performance_metric(
                pipeline="hf_sdxl_ip_adapter",
                stage=f"{pipeline_kind}_inference",
                request_id=request_id,
                provider="hf",
                model=self._model_key,
                elapsed_ms=elapsed_ms,
                success=True,
                extra=extra,
            )
            logger.info(
                "hf_sdxl_generation_completed | pipeline_kind={} | generated_count={} | "
                "elapsed_ms={:.2f} | peak_allocated_gb={} | peak_reserved_gb={} | "
                "process_rss_gb={}",
                pipeline_kind,
                len(output_images),
                elapsed_ms,
                memory.get("gpu_peak_allocated_gb"),
                memory.get("gpu_peak_reserved_gb"),
                memory.get("process_rss_gb"),
            )
            return output_images
        except AppException:
            raise
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            memory = self._memory_stats()
            record_performance_metric(
                pipeline="hf_sdxl_ip_adapter",
                stage=f"{pipeline_kind}_inference",
                request_id=request_id,
                provider="hf",
                model=self._model_key,
                elapsed_ms=elapsed_ms,
                success=False,
                error_code="HF_SDXL_IP_ADAPTER_GENERATION_FAILED",
                error_type=exc.__class__.__name__,
                extra={
                    "provider_type": "sdxl_ip_adapter",
                    "pipeline_kind": pipeline_kind,
                    "requested_size": requested_size,
                    "native_size": used_native_size,
                    "strength": strength,
                    "oom_fallback_used": fallback_used,
                    **memory,
                },
            )
            raise AppException(
                errors.HF_IMAGE_GENERATION_FAILED,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "provider_type": "sdxl_ip_adapter",
                    "pipeline_kind": pipeline_kind,
                    "model_name": self._model_key,
                    "error": str(exc),
                },
            ) from exc
