"""
HF 이미지 생성 provider.
"""
from __future__ import annotations

import os
import threading
from typing import Any

from loguru import logger
import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageOps
from starlette.concurrency import run_in_threadpool

from app.core import error_constants as errors
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.model_config import get_model_settings, get_provider_section
from app.services.providers.base import ImageGenerationProvider, ImageRenderMode
from app.utils.image_bytes import image_bytes_to_pil, pil_image_to_png_bytes


try:
    import torch
    from diffusers import (
        StableDiffusion3Img2ImgPipeline,
        StableDiffusion3InpaintPipeline,
        StableDiffusion3Pipeline,
    )

    _TORCH_DIFFUSERS_IMPORT_ERROR: Exception | None = None

except ImportError as _import_exc:
    torch = None
    StableDiffusion3Pipeline = None
    StableDiffusion3InpaintPipeline = None
    StableDiffusion3Img2ImgPipeline = None
    _TORCH_DIFFUSERS_IMPORT_ERROR = _import_exc


_TEXT2IMG_PIPELINE_CACHE: dict[tuple[str, str, str], Any] = {}
_INPAINT_PIPELINE_CACHE: dict[tuple[str, str, str], Any] = {}
_IMG2IMG_PIPELINE_CACHE: dict[tuple[str, str, str], Any] = {}
_PIPELINE_LOAD_LOCK = threading.RLock()
_PIPELINE_INFERENCE_LOCK = threading.Lock()
DEFAULT_NEGATIVE_PROMPT = (
    "blurry, low quality, distorted, deformed, "
    "gibberish text, garbled text, misspelled text, unreadable text, "
    "watermark, logo, signature, "
    "people, human hands, fingers, body parts"
)

BACKDROP_ONLY_NEGATIVE_PROMPT = (
    "cup, mug, glass, tumbler, bottle, can, jar, straw, "
    "drink, beverage, cocktail, coffee, tea, "
    "food, dish, plate, bowl, dessert, cake, pastry, "
    "utensils, cutlery, tableware, product, packaging, "
    "duplicate object, second product, extra product, cloned item"
)

BACKDROP_ONLY_PROMPT_SUFFIX = (
    ", empty backdrop only, completely empty foreground and center area, "
    "no cup, no glass, no drink, no food, no plate, nothing placed on the surface yet, "
    "leave the center area clean and unobstructed so a product photo can be added later, "
    "focus only on background texture, table/surface, props at the edges, lighting and color palette"
)


class HFImageProvider(ImageGenerationProvider):
    """
    HuggingFace(diffusers) 기반 이미지 생성 provider.
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

        self._subject_height_ratio = float(self._settings.get("subject_height_ratio", 0.62))
        self._subject_max_width_ratio = float(self._settings.get("subject_max_width_ratio", 0.86))
        self._subject_bottom_margin_ratio = float(self._settings.get("subject_bottom_margin_ratio", 0.08))
        self._subject_alpha_full_threshold = float(self._settings.get("subject_alpha_full_threshold", 0.97))

        self._mask_feather_px = int(self._settings.get("mask_feather_px", 6))
        self._composite_feather_px = int(self._settings.get("composite_feather_px", 3))

        self._color_harmonize_strength = max(
            0.0,
            min(1.0, float(self._settings.get("color_harmonize_strength", 0.35))),
        )

        self._drop_shadow_opacity = max(
            0.0,
            min(1.0, float(self._settings.get("drop_shadow_opacity", 0.3))),
        )
        self._drop_shadow_blur_px = int(self._settings.get("drop_shadow_blur_px", 16))
        self._drop_shadow_offset_y = int(self._settings.get("drop_shadow_offset_y", 14))

        self._seam_blend_enabled = bool(self._settings.get("seam_blend_enabled", True))
        self._seam_ring_px = int(self._settings.get("seam_ring_px", 24))
        self._seam_blend_strength = float(self._settings.get("seam_blend_strength", 0.35))
        self._seam_num_inference_steps = int(
            self._settings.get("seam_num_inference_steps", self._num_inference_steps)
        )

        self._img2img_restyle_strength = float(self._settings.get("img2img_restyle_strength", 0.35))

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

        env_token = os.environ.get(token_env)

        if env_token is not None:
            return env_token.strip()

        settings_token = get_settings().hf_token

        if settings_token:
            return settings_token.strip()

        return ""

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

        if StableDiffusion3InpaintPipeline is None:
            raise AppException(
                errors.HF_IMAGE_PIPELINE_DEPENDENCY_ERROR,
                detail={
                    "reason": "StableDiffusion3InpaintPipeline import 실패",
                    "hint": "diffusers>=0.31 로 업그레이드가 필요합니다.",
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

    def _load_inpaint_pipeline(self):
        self._ensure_torch_and_diffusers_available()

        dtype = self._resolve_torch_dtype()
        device = self._resolve_device()
        cache_key = (self._model_id, str(dtype), device)

        cached = _INPAINT_PIPELINE_CACHE.get(cache_key)
        if cached is not None:
            return cached

        with _PIPELINE_LOAD_LOCK:
            cached = _INPAINT_PIPELINE_CACHE.get(cache_key)
            if cached is not None:
                return cached

            text2img_pipe = self._load_text2img_pipeline()

            try:
                inpaint_pipe = StableDiffusion3InpaintPipeline(**text2img_pipe.components)

                if device == "cuda":
                    inpaint_pipe.to(device)
                else:
                    inpaint_pipe.enable_model_cpu_offload()

            except Exception as exc:
                raise AppException(
                    errors.HF_IMAGE_MODEL_LOAD_FAILED,
                    detail={
                        "provider": "hf", "role": "image_generation",
                        "model_id": self._model_id, "stage": "inpaint_pipeline_init",
                        "error": str(exc),
                    },
                ) from exc

            _INPAINT_PIPELINE_CACHE[cache_key] = inpaint_pipe
            logger.info(
                "hf_inpaint_pipeline_loaded | model_id={} | device={}",
                self._model_id,
                device,
            )
            return inpaint_pipe

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
            logger.info("hf_img2img_pipeline_loaded | model_id={} | device={}", self._model_id, device)
            return img2img_pipe


    async def generate_backgrounds(
        self,
        *,
        prompt: str,
        num_images: int,
    ) -> list[bytes]:
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
        size: str | None = None,
        negative_prompt: str | None = None,
        render_mode: ImageRenderMode = "photo_restyle",
    ) -> list[bytes]:
        _ = size
        return await run_in_threadpool(
            self._generate_sync,
            input_image_bytes=input_image_bytes,
            prompt=prompt,
            num_images=num_images,
            mask_image_bytes=mask_image_bytes,
            negative_prompt=negative_prompt,
            render_mode=render_mode,
        )


    def _build_blend_alpha(self, subject_alpha: Image.Image) -> Image.Image:
        if self._composite_feather_px <= 0:
            return subject_alpha
        return subject_alpha.filter(ImageFilter.GaussianBlur(self._composite_feather_px))

    def _harmonize_subject_colors(
        self,
        *,
        subject_rgb: Image.Image,
        background_rgb: Image.Image,
        subject_mask_l: Image.Image,
    ) -> Image.Image:
        strength = self._color_harmonize_strength

        if strength <= 0:
            return subject_rgb

        subject_np = np.asarray(subject_rgb, dtype=np.float64)
        background_np = np.asarray(background_rgb, dtype=np.float64)
        weight_np = np.asarray(subject_mask_l, dtype=np.float64)[..., None] / 255.0

        weight_sum = float(np.clip(weight_np.sum(), 1e-6, None))
        subject_mean = (subject_np * weight_np).sum(axis=(0, 1)) / weight_sum
        subject_var = (
            ((subject_np - subject_mean) ** 2) * weight_np
        ).sum(axis=(0, 1)) / weight_sum
        subject_std = np.sqrt(np.clip(subject_var, 1e-6, None))

        background_mean = background_np.reshape(-1, 3).mean(axis=0)
        background_std = np.clip(background_np.reshape(-1, 3).std(axis=0), 1e-6, None)

        normalized = (subject_np - subject_mean) / subject_std
        color_matched = normalized * background_std + background_mean

        blended = subject_np * (1 - strength) + color_matched * strength
        blended = np.clip(blended, 0, 255).astype(np.uint8)

        return Image.fromarray(blended, mode="RGB")

    def _apply_drop_shadow(
        self,
        *,
        background_rgb: Image.Image,
        subject_alpha: Image.Image,
    ) -> Image.Image:
        if self._drop_shadow_opacity <= 0:
            return background_rgb

        canvas = background_rgb.convert("RGBA")

        shadow_alpha = subject_alpha.point(
            lambda pixel_value: int(pixel_value * self._drop_shadow_opacity)
        )
        shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 255))
        shadow_layer.putalpha(shadow_alpha)

        offset_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        offset_layer.paste(shadow_layer, (0, self._drop_shadow_offset_y))
        offset_layer = offset_layer.filter(
            ImageFilter.GaussianBlur(self._drop_shadow_blur_px)
        )

        composed = Image.alpha_composite(canvas, offset_layer)
        return composed.convert("RGB")


    @staticmethod
    def _alpha_opaque_ratio(alpha: Image.Image) -> float:
        histogram = alpha.histogram()
        total = sum(histogram)
        if total == 0:
            return 1.0
        opaque = sum(histogram[250:256])
        return opaque / total

    def _fit_subject_to_canvas(
        self,
        *,
        source_rgba: Image.Image,
        mask_alpha: Image.Image,
        canvas_size: tuple[int, int],
    ) -> tuple[Image.Image, Image.Image]:
        canvas_w, canvas_h = canvas_size

        if mask_alpha.size != source_rgba.size:
            mask_alpha = mask_alpha.resize(source_rgba.size)

        bbox = mask_alpha.getbbox()
        if bbox is None:
            bbox = (0, 0, source_rgba.width, source_rgba.height)

        cropped_subject = source_rgba.crop(bbox)
        cropped_alpha = mask_alpha.crop(bbox)

        subject_w = max(1, cropped_subject.width)
        subject_h = max(1, cropped_subject.height)

        target_h = max(1, int(canvas_h * self._subject_height_ratio))
        scale = target_h / subject_h
        target_w = max(1, int(subject_w * scale))

        max_w = max(1, int(canvas_w * self._subject_max_width_ratio))
        if target_w > max_w:
            scale = max_w / subject_w
            target_w = max_w
            target_h = max(1, int(subject_h * scale))

        resized_subject = cropped_subject.resize((target_w, target_h), Image.Resampling.LANCZOS)
        resized_alpha = cropped_alpha.resize((target_w, target_h), Image.Resampling.LANCZOS)

        anchor_x = max(0, (canvas_w - target_w) // 2)
        bottom_margin = int(canvas_h * self._subject_bottom_margin_ratio)
        anchor_y = max(0, canvas_h - target_h - bottom_margin)

        canvas_subject = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        canvas_alpha = Image.new("L", canvas_size, 0)

        canvas_subject.paste(resized_subject, (anchor_x, anchor_y), resized_alpha)
        canvas_alpha.paste(resized_alpha, (anchor_x, anchor_y))

        return canvas_subject, canvas_alpha

    def _compose_subject_on_backdrop(
        self,
        *,
        backdrop_rgb: Image.Image,
        subject_rgba: Image.Image,
        subject_alpha: Image.Image,
    ) -> Image.Image:
        blend_alpha = self._build_blend_alpha(subject_alpha)

        harmonized_subject = self._harmonize_subject_colors(
            subject_rgb=subject_rgba.convert("RGB"),
            background_rgb=backdrop_rgb,
            subject_mask_l=subject_alpha,
        )

        shadowed_background = self._apply_drop_shadow(
            background_rgb=backdrop_rgb,
            subject_alpha=subject_alpha,
        )

        return Image.composite(harmonized_subject, shadowed_background, blend_alpha)


    @staticmethod
    def _odd(value: int) -> int:
        value = max(1, int(value))
        return value if value % 2 == 1 else value + 1

    def _build_seam_ring_mask(
        self,
        subject_alpha: Image.Image,
        ring_px: int,
    ) -> Image.Image | None:
        if ring_px <= 0:
            return None

        binary_alpha = subject_alpha.point(lambda p: 255 if p >= 128 else 0)

        kernel = self._odd(ring_px)
        dilated = binary_alpha.filter(ImageFilter.MaxFilter(kernel))
        eroded = binary_alpha.filter(ImageFilter.MinFilter(kernel))

        ring = ImageChops.subtract(dilated, eroded)
        ring = ring.filter(ImageFilter.GaussianBlur(max(1, ring_px // 3)))

        return ring

    def _seam_blend(
        self,
        *,
        composited_rgb: Image.Image,
        subject_alpha: Image.Image,
        prompt: str,
        negative_prompt: str | None,
    ) -> Image.Image:
        seam_mask = self._build_seam_ring_mask(subject_alpha, self._seam_ring_px)

        if seam_mask is None:
            return composited_rgb

        pipe = self._load_inpaint_pipeline()

        with _PIPELINE_INFERENCE_LOCK:
            result = pipe(
                prompt=prompt,
                negative_prompt=negative_prompt or DEFAULT_NEGATIVE_PROMPT,
                image=composited_rgb,
                mask_image=seam_mask,
                strength=self._seam_blend_strength,
                num_inference_steps=self._seam_num_inference_steps,
                guidance_scale=self._guidance_scale,
                max_sequence_length=self._max_sequence_length,
                num_images_per_prompt=1,
            )

        images = list(getattr(result, "images", []) or [])
        if not images:
            return composited_rgb

        return images[0].convert("RGB").resize(composited_rgb.size)


    @staticmethod
    def _build_backdrop_prompt(prompt: str) -> str:
        return f"{prompt}{BACKDROP_ONLY_PROMPT_SUFFIX}"

    @staticmethod
    def _build_backdrop_negative_prompt(negative_prompt: str | None) -> str:
        base = negative_prompt or DEFAULT_NEGATIVE_PROMPT
        return f"{base}, {BACKDROP_ONLY_NEGATIVE_PROMPT}"

    def _generate_backdrops(
        self,
        *,
        prompt: str,
        negative_prompt: str | None,
        canvas_size: tuple[int, int],
        num_images: int,
    ) -> list[Image.Image]:
        pipe = self._load_text2img_pipeline()

        backdrop_prompt = self._build_backdrop_prompt(prompt)
        backdrop_negative_prompt = self._build_backdrop_negative_prompt(negative_prompt)

        try:
            with _PIPELINE_INFERENCE_LOCK:
                result = pipe(
                    prompt=backdrop_prompt,
                    negative_prompt=backdrop_negative_prompt,
                    num_inference_steps=self._num_inference_steps,
                    guidance_scale=self._guidance_scale,
                    height=canvas_size[1],
                    width=canvas_size[0],
                    max_sequence_length=self._max_sequence_length,
                    num_images_per_prompt=num_images,
                )

        except AppException:
            raise

        except Exception as exc:
            logger.exception(
                "hf_backdrop_generation_failed | model_id={} | error={}",
                self._model_id,
                str(exc),
            )
            raise AppException(
                errors.HF_IMAGE_GENERATION_FAILED,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "model_id": self._model_id,
                    "stage": "backdrop_generation",
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
                    "stage": "backdrop_generation",
                },
            )

        return [image.convert("RGB") for image in images]


    def _restyle_whole_image(
        self,
        *,
        source_rgba: Image.Image,
        prompt: str,
        negative_prompt: str | None,
        canvas_size: tuple[int, int],
        num_images: int,
    ) -> list[bytes]:
        pipe = self._load_img2img_pipeline()

        base_image = ImageOps.fit(
            source_rgba.convert("RGB"),
            canvas_size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

        try:
            with _PIPELINE_INFERENCE_LOCK:
                result = pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt or DEFAULT_NEGATIVE_PROMPT,
                    image=base_image,
                    strength=self._img2img_restyle_strength,
                    guidance_scale=self._guidance_scale,
                    num_inference_steps=self._num_inference_steps,
                    num_images_per_prompt=num_images,
                )

        except AppException:
            raise

        except Exception as exc:
            logger.exception(
                "hf_restyle_generation_failed | model_id={} | error={}",
                self._model_id,
                str(exc),
            )
            raise AppException(
                errors.HF_IMAGE_GENERATION_FAILED,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "model_id": self._model_id,
                    "stage": "restyle_whole_image",
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
                    "stage": "restyle_whole_image",
                },
            )

        return [
            pil_image_to_png_bytes(image.convert("RGB").resize(canvas_size))
            for image in images
        ]


    def _generate_sync(
        self,
        *,
        input_image_bytes: bytes,
        prompt: str,
        num_images: int,
        mask_image_bytes: bytes | None = None,
        negative_prompt: str | None = None,
        render_mode: ImageRenderMode = "photo_restyle",
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

        source_rgba = image_bytes_to_pil(input_image_bytes).convert("RGBA")
        canvas_size = (self._width, self._height)

        if render_mode == "photo_restyle":
            return self._restyle_whole_image(
                source_rgba=source_rgba,
                prompt=prompt,
                negative_prompt=negative_prompt,
                canvas_size=canvas_size,
                num_images=num_images,
            )

        if render_mode != "background_swap":
            raise ValueError(f"Unsupported render_mode: {render_mode}")

        mask_source = (
            image_bytes_to_pil(mask_image_bytes).convert("RGBA")
            if mask_image_bytes
            else source_rgba
        )
        if mask_source.size != source_rgba.size:
            mask_source = mask_source.resize(source_rgba.size)

        raw_subject_alpha = mask_source.split()[-1]
        canvas_size = (self._width, self._height)

        alpha_opaque_ratio = self._alpha_opaque_ratio(raw_subject_alpha)

        logger.info(
            "hf_image_generation_started | model_id={} | num_images={} | "
            "has_mask={} | alpha_opaque_ratio={:.3f}",
            self._model_id,
            num_images,
            bool(mask_image_bytes),
            alpha_opaque_ratio,
        )

        canvas_subject, canvas_alpha = self._fit_subject_to_canvas(
            source_rgba=source_rgba,
            mask_alpha=raw_subject_alpha,
            canvas_size=canvas_size,
        )

        backdrops = self._generate_backdrops(
            prompt=prompt,
            negative_prompt=negative_prompt,
            canvas_size=canvas_size,
            num_images=num_images,
        )

        output_images: list[bytes] = []

        for backdrop_rgb in backdrops:
            composited = self._compose_subject_on_backdrop(
                backdrop_rgb=backdrop_rgb,
                subject_rgba=canvas_subject,
                subject_alpha=canvas_alpha,
            )

            if self._seam_blend_enabled:
                try:
                    composited = self._seam_blend(
                        composited_rgb=composited,
                        subject_alpha=canvas_alpha,
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                    )
                except Exception as exc:
                    logger.warning(
                        "hf_seam_blend_failed | model_id={} | error={} | fallback_to_composited",
                        self._model_id,
                        str(exc),
                    )

            output_images.append(pil_image_to_png_bytes(composited))

        logger.info(
            "hf_image_generation_completed | model_id={} | generated_count={}",
            self._model_id,
            len(output_images),
        )

        return output_images
