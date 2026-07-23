"""
SD1.5 + ControlNet Tile v1.1 로컬 이미지 생성 Provider.
"""
from __future__ import annotations

import gc
import os
import threading
import time
import uuid
from typing import Any

from loguru import logger
from PIL import Image
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


# ------------------------------------------------------------
# Optional dependency import
# ------------------------------------------------------------
try:
    import torch
    from diffusers import (
        ControlNetModel,
        DDIMScheduler,
        StableDiffusionControlNetPipeline,
    )

    _SD15_IMPORT_ERROR: Exception | None = None

except ImportError as _import_exc:
    torch = None
    ControlNetModel = None
    DDIMScheduler = None
    StableDiffusionControlNetPipeline = None
    _SD15_IMPORT_ERROR = _import_exc


# ------------------------------------------------------------
# Pipeline cache / lock
# ------------------------------------------------------------
_SD15_PIPELINE_CACHE: dict[
    tuple[str, str, str, str, bool, bool],
    tuple[Any, dict[str, Any]],
] = {}
_SD15_PIPELINE_LOAD_LOCK = threading.RLock()
_SD15_PIPELINE_INFERENCE_LOCK = threading.Lock()


DEFAULT_NEGATIVE_PROMPT = (
    "blurry, low quality, distorted, deformed, bad anatomy, "
    "text artifacts, watermark, logo, signature, unreadable text, "
    "oversaturated, plastic texture, fake 3d render"
)


class HFSD15ControlNetTileImageProvider(ImageGenerationProvider):
    """
    ControlNet Tile v1.1 + SD 1.5 기반 이미지 생성 Provider.
    """

    def __init__(
        self,
        *,
        model_name: str | None = None,
        model_settings: dict[str, Any] | None = None,
        hf_token: str | None = None,
    ) -> None:
        # ------------------------------------------------------------
        # 설정 로드
        # ------------------------------------------------------------
        self._settings = model_settings or {}
        self._model_key = str(model_name or "sd15_controlnet_tile")

        # SD 1.5 Base Model ID
        self._base_model_id = str(
            self._settings.get("base_model_id") or "runwayml/stable-diffusion-v1-5"
        )

        # ControlNet Tile Model ID
        self._controlnet_model_id = str(
            self._settings.get("controlnet_model_id") or "lllyasviel/control_v11f1e_sd15_tile"
        )

        # 실행 장치 / dtype
        self._device_setting = str(self._settings.get("device", "auto"))
        self._dtype_setting = str(self._settings.get("dtype", "fp16"))

        # 이미지 생성 기본값 (SD1.5 권장 기본 규격: 512x512)
        self._width = int(self._settings.get("width", 512))
        self._height = int(self._settings.get("height", 512))
        self._num_inference_steps = int(self._settings.get("num_inference_steps", 20))
        self._guidance_scale = float(self._settings.get("guidance_scale", 7.5))
        self._controlnet_conditioning_scale = float(
            self._settings.get("controlnet_conditioning_scale", 1.0)
        )
        self._num_images_per_prompt = int(self._settings.get("num_images_per_prompt", 1))

        # 최적화 옵션
        self._use_xformers = bool(self._settings.get("use_xformers", True))
        self._enable_vae_slicing = bool(self._settings.get("enable_vae_slicing", True))
        runtime_settings = get_settings()
        self._cpu_offload_enabled = runtime_settings.hf_image_cpu_offload_enabled
        self._min_available_ram_gb = runtime_settings.model_load_min_available_ram_gb

        # HF token 설정
        self._hf_token = hf_token or self._resolve_hf_token()

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

    # ------------------------------------------------------------
    # HF token resolution
    # ------------------------------------------------------------
    @staticmethod
    def _resolve_hf_token() -> str:
        hf_config = get_provider_section("hf")
        token_env = str(hf_config.get("token_env", "HF_TOKEN"))

        env_token = os.environ.get(token_env)
        if env_token is not None:
            return env_token.strip()

        settings_token = get_settings().hf_token
        if settings_token:
            return settings_token.strip()

        return ""

    # ------------------------------------------------------------
    # Dependency / device / dtype helpers
    # ------------------------------------------------------------
    def _ensure_dependencies_available(self) -> None:
        if _SD15_IMPORT_ERROR is not None:
            raise AppException(
                errors.HF_IMAGE_PIPELINE_DEPENDENCY_ERROR,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "model_name": self._model_key,
                    "reason": "sd15 controlnet dependencies import failed",
                    "hint": (
                        "requirements에 torch, diffusers, transformers, accelerate, "
                        "huggingface_hub가 필요합니다."
                    ),
                    "error": str(_SD15_IMPORT_ERROR),
                },
            )

    def _resolve_torch_dtype(self) -> Any:
        self._ensure_dependencies_available()

        mapping = {
            "auto": torch.float16,
            "fp16": torch.float16,
            "float16": torch.float16,
            "bf16": torch.bfloat16,
            "bfloat16": torch.bfloat16,
            "fp32": torch.float32,
            "float32": torch.float32,
        }

        return mapping.get(self._dtype_setting.lower(), torch.float16)

    def _resolve_device(self) -> str:
        self._ensure_dependencies_available()

        name = self._device_setting.lower()
        if name != "auto":
            return name

        if torch.cuda.is_available():
            return "cuda"

        mps_backend = getattr(torch.backends, "mps", None)
        if mps_backend is not None and mps_backend.is_available():
            return "mps"

        return "cpu"

    # ------------------------------------------------------------
    # Metric helpers
    # ------------------------------------------------------------
    @staticmethod
    def _memory_stats() -> dict[str, float | None]:
        return collect_memory_snapshot(torch_module=torch)

    def _parse_size(self, size: str | None) -> tuple[int, int]:
        if not size:
            return self._width, self._height

        normalized = size.lower().replace(" ", "")
        if "x" not in normalized:
            return self._width, self._height

        try:
            width_text, height_text = normalized.split("x", 1)
            width = int(width_text)
            height = int(height_text)

            if width <= 0 or height <= 0:
                return self._width, self._height

            return width, height

        except Exception:
            return self._width, self._height

    # ------------------------------------------------------------
    # Pipeline loading
    # ------------------------------------------------------------
    def _load_pipeline(self) -> tuple[Any, dict[str, Any]]:
        """
        SD 1.5 + ControlNet Tile v1.1 pipeline을 로드한다.
        """
        self._ensure_dependencies_available()

        dtype = self._resolve_torch_dtype()
        device = self._resolve_device()

        cache_key = (
            self._base_model_id,
            self._controlnet_model_id,
            str(dtype),
            device,
            bool(self._use_xformers),
            bool(self._cpu_offload_enabled),
        )

        cached = _SD15_PIPELINE_CACHE.get(cache_key)
        if cached is not None:
            return cached

        with _SD15_PIPELINE_LOAD_LOCK:
            cached = _SD15_PIPELINE_CACHE.get(cache_key)
            if cached is not None:
                return cached

            request_id = f"hf-sd15-load-{uuid.uuid4().hex[:10]}"
            started = time.perf_counter()

            logger.info(
                "hf_sd15_controlnet_pipeline_loading | model_key={} | base_model_id={} | "
                "controlnet_id={} | device={} | dtype={}",
                self._model_key,
                self._base_model_id,
                self._controlnet_model_id,
                device,
                str(dtype),
            )

            try:
                before_load = log_model_memory_snapshot(
                    "before_controlnet_load",
                    model_name=self._model_key,
                    torch_module=torch,
                )
                ensure_model_load_memory(
                    model_name=self._model_key,
                    min_available_ram_gb=self._min_available_ram_gb,
                    snapshot=before_load,
                    torch_module=torch,
                )

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.reset_peak_memory_stats()

                # 1. ControlNet 모델 로드
                controlnet = ControlNetModel.from_pretrained(
                    self._controlnet_model_id,
                    torch_dtype=dtype,
                    use_safetensors=False,
                    token=self._hf_token,
                    low_cpu_mem_usage=True,
                )
                log_model_memory_snapshot(
                    "after_controlnet_load",
                    model_name=self._model_key,
                    torch_module=torch,
                )

                # 2. Stable Diffusion ControlNet Pipeline 로드
                pipeline_kwargs: dict[str, Any] = {
                    "pretrained_model_name_or_path": self._base_model_id,
                    "controlnet": controlnet,
                    "torch_dtype": dtype,
                    "use_safetensors": True,
                    "token": self._hf_token,
                    "low_cpu_mem_usage": True,
                }

                if dtype == torch.float16:
                    pipeline_kwargs["variant"] = "fp16"

                pipe = StableDiffusionControlNetPipeline.from_pretrained(**pipeline_kwargs)
                log_model_memory_snapshot(
                    "after_pipeline_load",
                    model_name=self._model_key,
                    torch_module=torch,
                )

                del pipeline_kwargs
                del controlnet
                gc.collect()

                # DDIM Scheduler 구성
                pipe.scheduler = DDIMScheduler.from_config(pipe.scheduler.config)

                # 장치 이동
                log_model_memory_snapshot(
                    "before_pipe_to_device",
                    model_name=self._model_key,
                    torch_module=torch,
                )
                cpu_offload_enabled = self._cpu_offload_enabled and device == "cuda"
                if cpu_offload_enabled:
                    pipe.enable_model_cpu_offload()
                else:
                    if self._cpu_offload_enabled:
                        logger.warning(
                            "hf_sd15_cpu_offload_skipped | reason=cuda_unavailable | device={}",
                            device,
                        )
                    pipe = pipe.to(device)
                log_model_memory_snapshot(
                    "after_pipe_to_device",
                    model_name=self._model_key,
                    torch_module=torch,
                )

                # VAE slicing 적용
                if self._enable_vae_slicing:
                    try:
                        pipe.vae.enable_slicing()
                    except Exception as exc:
                        logger.warning(
                            "hf_sd15_vae_slicing_enable_failed | error={}",
                            str(exc),
                        )

                # xformers 적용
                xformers_enabled = False
                xformers_error = None
                if self._use_xformers:
                    try:
                        pipe.enable_xformers_memory_efficient_attention()
                        xformers_enabled = True
                    except Exception as exc:
                        xformers_error = f"{type(exc).__name__}: {exc}"
                        logger.warning(
                            "hf_sd15_xformers_enable_failed | error={}",
                            xformers_error,
                        )

                if torch.cuda.is_available():
                    torch.cuda.synchronize()

                elapsed_ms = (time.perf_counter() - started) * 1000

                meta = {
                    "provider_type": "sd15_controlnet_tile",
                    "base_model_id": self._base_model_id,
                    "controlnet_model_id": self._controlnet_model_id,
                    "xformers_enabled": xformers_enabled,
                    "xformers_error": xformers_error,
                    "device": device,
                    "dtype": str(dtype),
                    "cpu_offload_enabled": cpu_offload_enabled,
                }
                completion_snapshot = log_model_memory_snapshot(
                    "loading_complete",
                    model_name=self._model_key,
                    torch_module=torch,
                )
                meta.update(completion_snapshot)

                record_performance_metric(
                    pipeline="hf_sd15_controlnet_tile",
                    stage="model_load",
                    request_id=request_id,
                    provider="hf",
                    model=self._model_key,
                    elapsed_ms=elapsed_ms,
                    success=True,
                    extra=meta,
                )

                _SD15_PIPELINE_CACHE[cache_key] = (pipe, meta)

                logger.info(
                    "hf_sd15_controlnet_pipeline_loaded | model_key={} | device={} | "
                    "xformers_enabled={} | elapsed_ms={:.2f}",
                    self._model_key,
                    device,
                    xformers_enabled,
                    elapsed_ms,
                )

                return pipe, meta

            except AppException as exc:
                elapsed_ms = (time.perf_counter() - started) * 1000
                failure_snapshot = log_model_memory_snapshot(
                    "loading_failed",
                    model_name=self._model_key,
                    torch_module=torch,
                )
                record_performance_metric(
                    pipeline="hf_sd15_controlnet_tile",
                    stage="model_load",
                    request_id=request_id,
                    provider="hf",
                    model=self._model_key,
                    elapsed_ms=elapsed_ms,
                    success=False,
                    error_code=exc.code,
                    error_type=exc.__class__.__name__,
                    extra={
                        "provider_type": "sd15_controlnet_tile",
                        "base_model_id": self._base_model_id,
                        "controlnet_model_id": self._controlnet_model_id,
                        **failure_snapshot,
                    },
                )
                raise

            except Exception as exc:
                elapsed_ms = (time.perf_counter() - started) * 1000
                failure_snapshot = log_model_memory_snapshot(
                    "loading_failed",
                    model_name=self._model_key,
                    torch_module=torch,
                )

                logger.exception(
                    "hf_sd15_controlnet_pipeline_load_failed | model_key={} | error={}",
                    self._model_key,
                    str(exc),
                )

                record_performance_metric(
                    pipeline="hf_sd15_controlnet_tile",
                    stage="model_load",
                    request_id=request_id,
                    provider="hf",
                    model=self._model_key,
                    elapsed_ms=elapsed_ms,
                    success=False,
                    error_code="HF_SD15_CONTROLNET_MODEL_LOAD_FAILED",
                    error_type=exc.__class__.__name__,
                    extra={
                        "provider_type": "sd15_controlnet_tile",
                        "base_model_id": self._base_model_id,
                        "controlnet_model_id": self._controlnet_model_id,
                        **failure_snapshot,
                    },
                )

                raise AppException(
                    errors.HF_IMAGE_MODEL_LOAD_FAILED,
                    detail={
                        "provider": "hf",
                        "role": "image_generation",
                        "model_name": self._model_key,
                        "provider_type": "sd15_controlnet_tile",
                        "error": str(exc),
                    },
                ) from exc

    # ------------------------------------------------------------
    # Text-to-image / Dummy entrypoint
    # ------------------------------------------------------------
    async def generate_backgrounds(
        self,
        *,
        prompt: str,
        num_images: int,
    ) -> list[bytes]:
        """
        ControlNet Tile은 조건을 설정할 입력 이미지가 필요합니다.
        입력 이미지가 없는 백그라운드 생성 시 에러를 반환하거나 기본 캔버스를 처리해야 합니다.
        """
        raise AppException(
            errors.IMAGE_INPUT_FILE_NOT_FOUND,
            detail={
                "provider": "hf",
                "role": "image_generation",
                "provider_type": "sd15_controlnet_tile",
                "reason": "controlnet_tile_requires_input_image",
            },
        )

    # ------------------------------------------------------------
    # Image-conditioned generation entrypoint
    # ------------------------------------------------------------
    async def generate(
        self,
        *,
        input_image_bytes: bytes,
        prompt: str,
        num_images: int,
        mask_image_bytes: bytes | None = None,
        size: str | None = None,
        negative_prompt: str | None = None,
        render_mode: ImageRenderMode = "photo_restyle",
        img2img_strength: float | None = None,
    ) -> list[bytes]:
        _ = mask_image_bytes
        _ = render_mode
        _ = img2img_strength

        return await run_in_threadpool(
            self._generate_sync,
            input_image_bytes=input_image_bytes,
            prompt=prompt,
            num_images=num_images,
            size=size,
            negative_prompt=negative_prompt,
        )

    def _generate_sync(
        self,
        *,
        input_image_bytes: bytes,
        prompt: str,
        num_images: int,
        size: str | None = None,
        negative_prompt: str | None = None,
    ) -> list[bytes]:
        if not input_image_bytes:
            raise AppException(
                errors.IMAGE_INPUT_FILE_NOT_FOUND,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "provider_type": "sd15_controlnet_tile",
                    "reason": "input_image_bytes_empty",
                },
            )

        input_image = image_bytes_to_pil(input_image_bytes).convert("RGB")

        return self._generate_images_sync(
            input_image=input_image,
            prompt=prompt,
            negative_prompt=negative_prompt or DEFAULT_NEGATIVE_PROMPT,
            num_images=num_images,
            size=size,
        )

    # ------------------------------------------------------------
    # Core inference
    # ------------------------------------------------------------
    def _generate_images_sync(
        self,
        *,
        input_image: Image.Image,
        prompt: str,
        negative_prompt: str | None,
        num_images: int,
        size: str | None,
    ) -> list[bytes]:
        request_id = f"hf-sd15-gen-{uuid.uuid4().hex[:10]}"

        width, height = self._parse_size(size)
        effective_num_images = max(1, int(num_images or self._num_images_per_prompt))

        # ControlNet Tile 조건용 이미지 리사이징
        control_image = input_image.resize((width, height), Image.Resampling.LANCZOS)

        pipe, load_meta = self._load_pipeline()

        started = time.perf_counter()

        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats()

            kwargs: dict[str, Any] = {
                "prompt": prompt,
                "negative_prompt": negative_prompt or DEFAULT_NEGATIVE_PROMPT,
                "image": control_image,
                "width": width,
                "height": height,
                "num_inference_steps": self._num_inference_steps,
                "guidance_scale": self._guidance_scale,
                "controlnet_conditioning_scale": self._controlnet_conditioning_scale,
                "num_images_per_prompt": effective_num_images,
            }

            logger.info(
                "hf_sd15_controlnet_generation_started | model_key={} | width={} | height={} | "
                "num_images={} | conditioning_scale={}",
                self._model_key,
                width,
                height,
                effective_num_images,
                self._controlnet_conditioning_scale,
            )

            with _SD15_PIPELINE_INFERENCE_LOCK:
                result = pipe(**kwargs)

            if torch.cuda.is_available():
                torch.cuda.synchronize()

            elapsed_ms = (time.perf_counter() - started) * 1000

            images = list(getattr(result, "images", []) or [])
            if not images:
                raise AppException(
                    errors.IMAGE_GENERATION_EMPTY_RESULT,
                    detail={
                        "provider": "hf",
                        "role": "image_generation",
                        "provider_type": "sd15_controlnet_tile",
                        "model_name": self._model_key,
                    },
                )

            output_images = [
                pil_image_to_png_bytes(img.convert("RGB").resize((width, height)))
                for img in images
            ]

            extra = {
                **load_meta,
                "width": width,
                "height": height,
                "num_images": len(output_images),
                "num_inference_steps": self._num_inference_steps,
                "guidance_scale": self._guidance_scale,
                "controlnet_conditioning_scale": self._controlnet_conditioning_scale,
            }
            extra.update(self._memory_stats())

            record_performance_metric(
                pipeline="hf_sd15_controlnet_tile",
                stage="inference",
                request_id=request_id,
                provider="hf",
                model=self._model_key,
                elapsed_ms=elapsed_ms,
                success=True,
                extra=extra,
            )

            logger.info(
                "hf_sd15_controlnet_generation_completed | model_key={} | generated_count={} | "
                "elapsed_ms={:.2f} | gpu_peak_allocated_gb={} | gpu_peak_reserved_gb={}",
                self._model_key,
                len(output_images),
                elapsed_ms,
                extra.get("gpu_peak_allocated_gb"),
                extra.get("gpu_peak_reserved_gb"),
            )

            return output_images

        except AppException:
            raise

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000

            logger.exception(
                "hf_sd15_controlnet_generation_failed | model_key={} | error={}",
                self._model_key,
                str(exc),
            )

            record_performance_metric(
                pipeline="hf_sd15_controlnet_tile",
                stage="inference",
                request_id=request_id,
                provider="hf",
                model=self._model_key,
                elapsed_ms=elapsed_ms,
                success=False,
                error_code="HF_SD15_CONTROLNET_GENERATION_FAILED",
                error_type=exc.__class__.__name__,
                extra={
                    "provider_type": "sd15_controlnet_tile",
                    "width": width,
                    "height": height,
                    "xformers_enabled": load_meta.get("xformers_enabled"),
                },
            )

            raise AppException(
                errors.HF_IMAGE_GENERATION_FAILED,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "model_name": self._model_key,
                    "provider_type": "sd15_controlnet_tile",
                    "error": str(exc),
                },
            ) from exc
