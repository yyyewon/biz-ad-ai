"""
HF 이미지 생성 provider
"""
from __future__ import annotations

import os
import threading
from typing import Any

from loguru import logger
from PIL import Image
from starlette.concurrency import run_in_threadpool

from app.core import error_constants as errors
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.model_config import get_model_settings, get_provider_section
from app.services.providers.base import ImageGenerationProvider
from app.utils.image_bytes import image_bytes_to_pil, pil_image_to_png_bytes


try:
    import torch
    from diffusers import StableDiffusion3Img2ImgPipeline, StableDiffusion3Pipeline

    _TORCH_DIFFUSERS_IMPORT_ERROR: Exception | None = None

except ImportError as _import_exc:
    torch = None
    StableDiffusion3Pipeline = None
    StableDiffusion3Img2ImgPipeline = None
    _TORCH_DIFFUSERS_IMPORT_ERROR = _import_exc


_TEXT2IMG_PIPELINE_CACHE: dict[tuple[str, str, str], Any] = {}
_IMG2IMG_PIPELINE_CACHE: dict[tuple[str, str, str], Any] = {}
_PIPELINE_LOAD_LOCK = threading.RLock()
_PIPELINE_INFERENCE_LOCK = threading.Lock()


class HFImageProvider(ImageGenerationProvider):
    """
    HuggingFace(diffusers) 기반 이미지 생성 provider
    """

    def __init__(
        self,
        *,
        model_id: str | None = None,
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
        self._model_id = str(model_id or self._settings.get("model_id") or "")

        if not self._model_id:
            raise AppException(
                errors.MODEL_SETTINGS_NOT_FOUND,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "model_name": self._model_key,
                    "reason": "model_id_missing",
                },
            )

        self._device_setting = str(self._settings.get("device", "auto"))
        self._dtype_setting = str(self._settings.get("dtype", "auto"))

        self._width = int(self._settings.get("width", 1024))
        self._height = int(self._settings.get("height", 1024))
        self._num_inference_steps = int(self._settings.get("num_inference_steps", 40))
        self._guidance_scale = float(self._settings.get("guidance_scale", 4.5))
        self._max_sequence_length = int(self._settings.get("max_sequence_length", 512))
        self._img2img_strength = float(self._settings.get("img2img_strength", 0.65))

        self._hf_token = hf_token or self._resolve_hf_token()

        if not self._hf_token:
            raise AppException(
                errors.HF_TOKEN_MISSING,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "model_id": self._model_id,
                    "hint": (
                        "stable-diffusion-3.5-medium은 gated 모델입니다. "
                        "huggingface.co에서 라이선스 동의 후 .env의 HF_TOKEN을 설정하세요."
                    ),
                },
            )

    @staticmethod
    def _resolve_hf_token() -> str:
        hf_config = get_provider_section("hf")
        token_env = str(hf_config.get("token_env", "HF_TOKEN"))
        return os.getenv(token_env) or get_settings().hf_token

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height


    def _ensure_torch_and_diffusers_available(self) -> None:
        if _TORCH_DIFFUSERS_IMPORT_ERROR is not None:
            raise AppException(
                errors.HF_IMAGE_PIPELINE_DEPENDENCY_ERROR,
                detail={
                    "reason": "torch/diffusers import failed at server startup",
                    "hint": (
                        'requirements에 "torch", "diffusers", "transformers", '
                        '"accelerate", "sentencepiece"가 설치되어야 합니다.'
                    ),
                    "error": str(_TORCH_DIFFUSERS_IMPORT_ERROR),
                },
            )

    def _resolve_torch_dtype(self) -> Any:
        self._ensure_torch_and_diffusers_available()
        mapping = {
            "auto": torch.bfloat16,
            "bf16": torch.bfloat16,
            "bfloat16": torch.bfloat16,
            "fp16": torch.float16,
            "float16": torch.float16,
            "fp32": torch.float32,
            "float32": torch.float32,
        }
        return mapping.get(self._dtype_setting.lower(), torch.bfloat16)

    def _resolve_device(self) -> str:
        self._ensure_torch_and_diffusers_available()
        name = self._device_setting.lower()

        if name != "auto":
            return name
        if torch.cuda.is_available():
            return "cuda"
        mps_backend = getattr(torch.backends, "mps", None)
        if mps_backend is not None and mps_backend.is_available():
            return "mps"
        return "cpu"

    def _load_text2img_pipeline(self):
        self._ensure_torch_and_diffusers_available()

        dtype = self._resolve_torch_dtype()
        device = self._resolve_device()
        cache_key = (self._model_id, str(dtype), device)

        cached = _TEXT2IMG_PIPELINE_CACHE.get(cache_key)
        if cached is not None:
            return cached

        with _PIPELINE_LOAD_LOCK:
            cached = _TEXT2IMG_PIPELINE_CACHE.get(cache_key)
            if cached is not None:
                return cached

            logger.info(
                "hf_image_pipeline_loading | model_id={} | device={} | dtype={}",
                self._model_id, device, str(dtype),
            )

            try:
                pipe = StableDiffusion3Pipeline.from_pretrained(
                    self._model_id,
                    torch_dtype=dtype,
                    token=self._hf_token,
                    low_cpu_mem_usage=True,
                )

                if device == "cuda":
                    pipe.to(device)
                else:
                    pipe.enable_model_cpu_offload()

            except Exception as exc:
                raise AppException(
                    errors.HF_IMAGE_MODEL_LOAD_FAILED,
                    detail={
                        "provider": "hf", "role": "image_generation",
                        "model_id": self._model_id, "error": str(exc),
                    },
                ) from exc

            _TEXT2IMG_PIPELINE_CACHE[cache_key] = pipe
            logger.info("hf_image_pipeline_loaded | model_id={} | device={}", self._model_id, device)
            return pipe

    def _load_img2img_pipeline(self):
        self._ensure_torch_and_diffusers_available()

        dtype = self._resolve_torch_dtype()
        device = self._resolve_device()
        cache_key = (self._model_id, str(dtype), device)

        cached = _IMG2IMG_PIPELINE_CACHE.get(cache_key)
        if cached is not None:
            return cached

        with _PIPELINE_LOAD_LOCK:
            cached = _IMG2IMG_PIPELINE_CACHE.get(cache_key)
            if cached is not None:
                return cached

            text2img_pipe = self._load_text2img_pipeline()

            try:
                img2img_pipe = StableDiffusion3Img2ImgPipeline(**text2img_pipe.components)
                if device == "cuda":
                    img2img_pipe.to(device)
                else:
                    img2img_pipe.enable_model_cpu_offload()

            except Exception as exc:
                raise AppException(
                    errors.HF_IMAGE_MODEL_LOAD_FAILED,
                    detail={
                        "provider": "hf", "role": "image_generation",
                        "model_id": self._model_id, "stage": "img2img_pipeline_init",
                        "error": str(exc),
                    },
                ) from exc

            _IMG2IMG_PIPELINE_CACHE[cache_key] = img2img_pipe
            return img2img_pipe


    async def generate_backgrounds(
        self,
        *,
        prompt: str,
        num_images: int,
    ) -> list[bytes]:
        """
        순수 text-to-image로 배경/레퍼런스 이미지 생성
        """

        return await run_in_threadpool(
            self._generate_backgrounds_sync,
            prompt=prompt,
            num_images=num_images,
        )

    def _generate_backgrounds_sync(
        self,
        *,
        prompt: str,
        num_images: int,
    ) -> list[bytes]:
        pipe = self._load_text2img_pipeline()

        logger.info(
            "hf_background_generation_started | model_id={} | num_images={}",
            self._model_id,
            num_images,
        )

        try:
            with _PIPELINE_INFERENCE_LOCK:
                result = pipe(
                    prompt=prompt,
                    num_inference_steps=self._num_inference_steps,
                    guidance_scale=self._guidance_scale,
                    height=self._height,
                    width=self._width,
                    max_sequence_length=self._max_sequence_length,
                    num_images_per_prompt=num_images,
                )

        except AppException:
            raise

        except Exception as exc:
            logger.exception(
                "hf_background_generation_failed | model_id={} | error={}",
                self._model_id,
                str(exc),
            )
            raise AppException(
                errors.HF_IMAGE_GENERATION_FAILED,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "model_id": self._model_id,
                    "error": str(exc),
                },
            ) from exc

        images = list(getattr(result, "images", []) or [])

        if not images:
            raise AppException(
                errors.IMAGE_GENERATION_EMPTY_RESULT,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "model_id": self._model_id,
                },
            )

        logger.info(
            "hf_background_generation_completed | model_id={} | generated_count={}",
            self._model_id,
            len(images),
        )

        return [pil_image_to_png_bytes(image.convert("RGB")) for image in images]

    async def generate(
        self,
        *,
        input_image_bytes: bytes,
        prompt: str,
        num_images: int,
        mask_image_bytes: bytes | None = None,
    ) -> list[bytes]:
        """
        입력 이미지를 기반으로 광고 이미지 생성
        """

        return await run_in_threadpool(
            self._generate_sync,
            input_image_bytes=input_image_bytes,
            prompt=prompt,
            num_images=num_images,
            mask_image_bytes=mask_image_bytes,
        )

    def _generate_sync(
        self,
        *,
        input_image_bytes: bytes,
        prompt: str,
        num_images: int,
        mask_image_bytes: bytes | None = None,
    ) -> list[bytes]:
        if not input_image_bytes:
            raise AppException(
                errors.IMAGE_INPUT_FILE_NOT_FOUND,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "reason": "input_image_bytes_empty",
                },
            )

        source_image = image_bytes_to_pil(input_image_bytes).convert("RGB")
        resized_source = source_image.resize((self._width, self._height))

        pipe = self._load_img2img_pipeline()

        logger.info(
            "hf_image_generation_started | model_id={} | num_images={} | has_mask={}",
            self._model_id,
            num_images,
            bool(mask_image_bytes),
        )

        try:
            with _PIPELINE_INFERENCE_LOCK:
                result = pipe(
                    prompt=prompt,
                    image=resized_source,
                    strength=self._img2img_strength,
                    num_inference_steps=self._num_inference_steps,
                    guidance_scale=self._guidance_scale,
                    max_sequence_length=self._max_sequence_length,
                    num_images_per_prompt=num_images,
                )

        except AppException:
            raise

        except Exception as exc:
            logger.exception(
                "hf_image_generation_failed | model_id={} | error={}",
                self._model_id,
                str(exc),
            )
            raise AppException(
                errors.HF_IMAGE_GENERATION_FAILED,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "model_id": self._model_id,
                    "error": str(exc),
                },
            ) from exc

        generated_images = list(getattr(result, "images", []) or [])

        if not generated_images:
            raise AppException(
                errors.IMAGE_GENERATION_EMPTY_RESULT,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "model_id": self._model_id,
                },
            )

        output_images: list[bytes] = []

        for generated_image in generated_images:
            generated_rgb = generated_image.convert("RGB")

            if mask_image_bytes:
                composited = self._composite_with_mask(
                    original=resized_source,
                    generated=generated_rgb,
                    mask_image_bytes=mask_image_bytes,
                )
                output_images.append(pil_image_to_png_bytes(composited))
            else:
                output_images.append(pil_image_to_png_bytes(generated_rgb))

        logger.info(
            "hf_image_generation_completed | model_id={} | generated_count={}",
            self._model_id,
            len(output_images),
        )

        return output_images

    @staticmethod
    def _composite_with_mask(
        *,
        original: Image.Image,
        generated: Image.Image,
        mask_image_bytes: bytes,
    ) -> Image.Image:
        """
        마스크의 알파 채널을 기준으로 원본(피사체)과 생성 결과(배경)를 합성
        """

        mask_image = image_bytes_to_pil(mask_image_bytes).convert("RGBA")
        alpha_channel = mask_image.split()[-1].resize(generated.size)

        original_resized = original.convert("RGB").resize(generated.size)

        return Image.composite(original_resized, generated, alpha_channel)