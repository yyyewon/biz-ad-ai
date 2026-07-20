"""
SDXL Lightning 4-step + IP-Adapter + xformers 이미지 생성 Provider.

역할:
- SDXL base pipeline 로드
- ByteDance SDXL-Lightning 4-step UNet weight 주입
- 입력 이미지가 있으면 IP-Adapter로 이미지 조건 반영
- xformers 사용 가능 시 attention 최적화
- HF 이미지 생성 성능 로그에 시간/GPU 메모리/model weight 크기 기록
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
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
from app.utils.performance_logger import record_performance_metric


# ------------------------------------------------------------
# Optional dependency import
# ------------------------------------------------------------
# Docker/로컬 환경에 diffusers, torch, huggingface_hub 등이 없을 수 있으므로
# import 실패를 서버 시작 시 바로 터뜨리지 않고 Provider 실행 시 AppException으로 변환한다.
try:
    import torch
    from diffusers import (
        EulerDiscreteScheduler,
        StableDiffusionXLPipeline,
        UNet2DConditionModel,
    )
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file

    _SDXL_IMPORT_ERROR: Exception | None = None

except ImportError as _import_exc:
    torch = None
    EulerDiscreteScheduler = None
    StableDiffusionXLPipeline = None
    UNet2DConditionModel = None
    hf_hub_download = None
    load_file = None
    _SDXL_IMPORT_ERROR = _import_exc


# ------------------------------------------------------------
# Pipeline cache / lock
# ------------------------------------------------------------
# 모델 로딩은 비용이 크므로 프로세스 내 캐시한다.
# 동시에 여러 요청이 들어와도 모델을 중복 로드하지 않도록 lock을 사용한다.
_SDXL_PIPELINE_CACHE: dict[tuple[str, str, str, str, bool, bool, float], tuple[Any, dict[str, Any]]] = {}
_SDXL_PIPELINE_LOAD_LOCK = threading.RLock()
_SDXL_PIPELINE_INFERENCE_LOCK = threading.Lock()


DEFAULT_NEGATIVE_PROMPT = (
    "blurry, low quality, distorted, deformed, bad anatomy, "
    "text artifacts, watermark, logo, signature, unreadable text, "
    "oversaturated, plastic texture, fake 3d render"
)


class HFSDXLLightningImageProvider(ImageGenerationProvider):
    """
    SDXL Lightning 4-step 기반 이미지 생성 Provider.
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
        # model.yaml의 hf.image_generation.models.sdxl_lightning 설정을 읽는다.
        self._settings = model_settings or {}
        self._model_key = str(model_name or "sdxl_lightning")

        # Lightning checkpoint repo
        self._lightning_repo_id = str(
            self._settings.get("model_id") or "ByteDance/SDXL-Lightning"
        )

        # SDXL base pipeline repo
        self._base_model_id = str(
            self._settings.get("base_model_id") or "stabilityai/stable-diffusion-xl-base-1.0"
        )

        # Lightning 4-step UNet weight file
        self._lightning_checkpoint = str(
            self._settings.get("lightning_checkpoint") or "sdxl_lightning_4step_unet.safetensors"
        )

        # 실행 장치 / dtype
        self._device_setting = str(self._settings.get("device", "auto"))
        self._dtype_setting = str(self._settings.get("dtype", "fp16"))

        # 이미지 생성 기본값
        self._width = int(self._settings.get("width", 1024))
        self._height = int(self._settings.get("height", 1024))
        self._num_inference_steps = int(self._settings.get("num_inference_steps", 4))
        self._guidance_scale = float(self._settings.get("guidance_scale", 0.0))
        self._num_images_per_prompt = int(self._settings.get("num_images_per_prompt", 1))

        # Scheduler 설정
        scheduler_settings = self._settings.get("scheduler", {}) or {}
        self._scheduler_timestep_spacing = str(
            scheduler_settings.get("timestep_spacing", "trailing")
        )

        # 최적화 옵션
        self._use_xformers = bool(self._settings.get("use_xformers", True))
        self._enable_vae_slicing = bool(self._settings.get("enable_vae_slicing", True))

        # IP-Adapter 설정
        self._ip_adapter_settings = self._settings.get("ip_adapter", {}) or {}
        self._ip_adapter_enabled = bool(self._ip_adapter_settings.get("enabled", True))
        self._ip_adapter_repo_id = str(
            self._ip_adapter_settings.get("repo_id") or "h94/IP-Adapter"
        )
        self._ip_adapter_subfolder = str(
            self._ip_adapter_settings.get("subfolder") or "sdxl_models"
        )
        self._ip_adapter_weight_name = str(
            self._ip_adapter_settings.get("weight_name") or "ip-adapter_sdxl.bin"
        )
        self._ip_adapter_image_encoder_folder = str(
            self._ip_adapter_settings.get("image_encoder_folder") or "sdxl_models/image_encoder"
        )
        self._ip_adapter_image_encoder_weight_name = str(
            self._ip_adapter_settings.get("image_encoder_weight_name") or "model.safetensors"
        )
        self._ip_adapter_scale = float(self._ip_adapter_settings.get("scale", 0.6))

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
        return self._lightning_repo_id

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
        """
        HF_TOKEN을 환경변수 또는 settings에서 가져온다.
        """

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
        """
        SDXL Provider 실행에 필요한 패키지 import 가능 여부를 확인한다.
        """

        if _SDXL_IMPORT_ERROR is not None:
            raise AppException(
                errors.HF_IMAGE_PIPELINE_DEPENDENCY_ERROR,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "model_name": self._model_key,
                    "reason": "sdxl dependencies import failed",
                    "hint": (
                        "requirements에 torch, diffusers, transformers, accelerate, "
                        "huggingface_hub, safetensors가 필요합니다."
                    ),
                    "error": str(_SDXL_IMPORT_ERROR),
                },
            )

    def _resolve_torch_dtype(self) -> Any:
        """
        model.yaml의 dtype 설정을 torch dtype으로 변환한다.
        """

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
        """
        실행 장치를 결정한다.
        auto이면 CUDA → MPS → CPU 순서로 선택한다.
        """

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
    def _bytes_to_mb(num_bytes: int) -> float:
        """
        byte 값을 MB로 변환한다.
        """

        return round(num_bytes / 1024 / 1024, 2)

    @classmethod
    def _file_size_mb(cls, path: str | Path | None) -> float:
        """
        weight/checkpoint 파일 크기를 MB 단위로 반환한다.
        """

        if not path:
            return 0.0

        file_path = Path(path)
        if not file_path.exists():
            return 0.0

        return cls._bytes_to_mb(file_path.stat().st_size)

    @staticmethod
    def _nvidia_smi_memory() -> dict[str, Any]:
        """
        nvidia-smi 기준 GPU memory 사용량을 조회한다.
        PyTorch 외부 CUDA context까지 포함한 운영 관점 지표다.
        """

        try:
            output = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
            ).strip()

            first = output.splitlines()[0]
            used_mb, total_mb = [int(value.strip()) for value in first.split(",")]

            return {
                "nvidia_smi_used_mb": used_mb,
                "nvidia_smi_total_mb": total_mb,
            }

        except Exception:
            return {
                "nvidia_smi_used_mb": None,
                "nvidia_smi_total_mb": None,
            }

    @staticmethod
    def _torch_gpu_stats() -> dict[str, Any]:
        """
        PyTorch CUDA allocator 기준 GPU memory 통계를 반환한다.

        - allocated: 실제 tensor가 사용 중인 메모리
        - reserved: PyTorch가 재사용을 위해 확보해 둔 메모리
        - peak_*: 측정 구간 내 최대값
        """

        if torch is None or not torch.cuda.is_available():
            return {
                "gpu_memory_allocated_gb": None,
                "gpu_memory_reserved_gb": None,
                "gpu_peak_allocated_gb": None,
                "gpu_peak_reserved_gb": None,
            }

        return {
            "gpu_memory_allocated_gb": round(torch.cuda.memory_allocated() / 1024**3, 3),
            "gpu_memory_reserved_gb": round(torch.cuda.memory_reserved() / 1024**3, 3),
            "gpu_peak_allocated_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
            "gpu_peak_reserved_gb": round(torch.cuda.max_memory_reserved() / 1024**3, 3),
        }

    def _parse_size(self, size: str | None) -> tuple[int, int]:
        """
        "1024x1024" 형태의 size 문자열을 width, height로 변환한다.
        실패하면 model.yaml 기본 크기를 사용한다.
        """

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
    def _load_pipeline(self, *, use_ip_adapter: bool) -> tuple[Any, dict[str, Any]]:
        """
        SDXL Lightning pipeline을 로드한다.

        흐름:
        1. SDXL base UNet config 로드
        2. SDXL Lightning 4-step UNet weight 다운로드
        3. UNet에 Lightning weight 주입
        4. SDXL base pipeline 생성
        5. Scheduler를 trailing timestep으로 교체
        6. xformers 활성화
        7. IP-Adapter 활성화
        8. 모델 로드 성능 로그 기록
        """

        self._ensure_dependencies_available()

        dtype = self._resolve_torch_dtype()
        device = self._resolve_device()

        # 같은 모델 조합은 한 번만 로드하기 위한 cache key
        cache_key = (
            self._base_model_id,
            self._lightning_checkpoint,
            str(dtype),
            device,
            bool(self._use_xformers),
            bool(use_ip_adapter),
            float(self._ip_adapter_scale),
        )

        cached = _SDXL_PIPELINE_CACHE.get(cache_key)
        if cached is not None:
            return cached

        with _SDXL_PIPELINE_LOAD_LOCK:
            cached = _SDXL_PIPELINE_CACHE.get(cache_key)
            if cached is not None:
                return cached

            request_id = f"hf-sdxl-load-{uuid.uuid4().hex[:10]}"
            started = time.perf_counter()

            logger.info(
                "hf_sdxl_lightning_pipeline_loading | model_key={} | base_model_id={} | "
                "lightning_repo={} | checkpoint={} | device={} | dtype={} | use_ip_adapter={}",
                self._model_key,
                self._base_model_id,
                self._lightning_repo_id,
                self._lightning_checkpoint,
                device,
                str(dtype),
                use_ip_adapter,
            )

            try:
                # GPU peak memory 측정 초기화
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.reset_peak_memory_stats()

                # Lightning checkpoint 다운로드
                lightning_checkpoint_path = hf_hub_download(
                    repo_id=self._lightning_repo_id,
                    filename=self._lightning_checkpoint,
                    token=self._hf_token,
                )

                # SDXL base UNet config 로드
                unet_config = UNet2DConditionModel.load_config(
                    self._base_model_id,
                    subfolder="unet",
                    token=self._hf_token,
                )

                # Lightning UNet 생성 및 weight 주입
                unet = UNet2DConditionModel.from_config(unet_config)
                state_dict = load_file(lightning_checkpoint_path, device="cpu")
                unet.load_state_dict(state_dict)
                unet = unet.to(device=device, dtype=dtype)

                # SDXL base pipeline 로드
                pipeline_kwargs: dict[str, Any] = {
                    "pretrained_model_name_or_path": self._base_model_id,
                    "unet": unet,
                    "torch_dtype": dtype,
                    "use_safetensors": True,
                    "token": self._hf_token,
                }

                if dtype == torch.float16:
                    pipeline_kwargs["variant"] = "fp16"

                pipe = StableDiffusionXLPipeline.from_pretrained(**pipeline_kwargs)

                # Lightning 4-step에 맞는 scheduler 설정
                pipe.scheduler = EulerDiscreteScheduler.from_config(
                    pipe.scheduler.config,
                    timestep_spacing=self._scheduler_timestep_spacing,
                )

                # 모델을 GPU/CPU/MPS로 이동
                pipe = pipe.to(device)

                # VAE slicing 적용
                if self._enable_vae_slicing:
                    try:
                        pipe.vae.enable_slicing()
                    except Exception as exc:
                        logger.warning(
                            "hf_sdxl_vae_slicing_enable_failed | error={}",
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
                            "hf_sdxl_xformers_enable_failed | error={}",
                            xformers_error,
                        )

                # IP-Adapter 로드
                ip_adapter_weight_path = None
                ip_adapter_image_encoder_path = None

                if use_ip_adapter:
                    # IP-Adapter weight 다운로드
                    ip_adapter_weight_path = hf_hub_download(
                        repo_id=self._ip_adapter_repo_id,
                        subfolder=self._ip_adapter_subfolder,
                        filename=self._ip_adapter_weight_name,
                        token=self._hf_token,
                    )

                    # SDXL용 image encoder weight 크기 측정용 다운로드
                    ip_adapter_image_encoder_path = hf_hub_download(
                        repo_id=self._ip_adapter_repo_id,
                        subfolder=self._ip_adapter_image_encoder_folder,
                        filename=self._ip_adapter_image_encoder_weight_name,
                        token=self._hf_token,
                    )

                    # Diffusers pipeline에 IP-Adapter 연결
                    pipe.load_ip_adapter(
                        self._ip_adapter_repo_id,
                        subfolder=self._ip_adapter_subfolder,
                        weight_name=self._ip_adapter_weight_name,
                        image_encoder_folder=self._ip_adapter_image_encoder_folder,
                    )

                    # 입력 이미지 영향도 설정
                    pipe.set_ip_adapter_scale(self._ip_adapter_scale)

                if torch.cuda.is_available():
                    torch.cuda.synchronize()

                elapsed_ms = (time.perf_counter() - started) * 1000

                # 모델 weight 크기 측정
                lightning_checkpoint_mb = self._file_size_mb(lightning_checkpoint_path)
                ip_adapter_weight_mb = self._file_size_mb(ip_adapter_weight_path)
                ip_adapter_image_encoder_mb = self._file_size_mb(ip_adapter_image_encoder_path)
                total_extra_weight_mb = round(
                    lightning_checkpoint_mb
                    + ip_adapter_weight_mb
                    + ip_adapter_image_encoder_mb,
                    2,
                )

                # 모델 로드 메타데이터 구성
                meta = {
                    "provider_type": "sdxl_lightning",
                    "base_model_id": self._base_model_id,
                    "lightning_repo_id": self._lightning_repo_id,
                    "lightning_checkpoint": self._lightning_checkpoint,
                    "lightning_checkpoint_mb": lightning_checkpoint_mb,
                    "ip_adapter_enabled": use_ip_adapter,
                    "ip_adapter_repo_id": self._ip_adapter_repo_id if use_ip_adapter else None,
                    "ip_adapter_weight_mb": ip_adapter_weight_mb,
                    "ip_adapter_image_encoder_mb": ip_adapter_image_encoder_mb,
                    "total_extra_weight_mb": total_extra_weight_mb,
                    "xformers_enabled": xformers_enabled,
                    "xformers_error": xformers_error,
                    "device": device,
                    "dtype": str(dtype),
                }
                meta.update(self._torch_gpu_stats())
                meta.update(self._nvidia_smi_memory())

                # 모델 로드 성능 로그 기록
                record_performance_metric(
                    pipeline="hf_sdxl_lightning",
                    stage="model_load",
                    request_id=request_id,
                    provider="hf",
                    model=self._model_key,
                    elapsed_ms=elapsed_ms,
                    success=True,
                    extra=meta,
                )

                _SDXL_PIPELINE_CACHE[cache_key] = (pipe, meta)

                logger.info(
                    "hf_sdxl_lightning_pipeline_loaded | model_key={} | device={} | "
                    "xformers_enabled={} | ip_adapter_enabled={} | elapsed_ms={:.2f}",
                    self._model_key,
                    device,
                    xformers_enabled,
                    use_ip_adapter,
                    elapsed_ms,
                )

                return pipe, meta

            except AppException:
                raise

            except Exception as exc:
                # 모델 로드 실패 로그 기록
                elapsed_ms = (time.perf_counter() - started) * 1000

                logger.exception(
                    "hf_sdxl_lightning_pipeline_load_failed | model_key={} | error={}",
                    self._model_key,
                    str(exc),
                )

                record_performance_metric(
                    pipeline="hf_sdxl_lightning",
                    stage="model_load",
                    request_id=request_id,
                    provider="hf",
                    model=self._model_key,
                    elapsed_ms=elapsed_ms,
                    success=False,
                    error_code="HF_SDXL_LIGHTNING_MODEL_LOAD_FAILED",
                    error_type=exc.__class__.__name__,
                    extra={
                        "provider_type": "sdxl_lightning",
                        "base_model_id": self._base_model_id,
                        "lightning_repo_id": self._lightning_repo_id,
                        "lightning_checkpoint": self._lightning_checkpoint,
                        "ip_adapter_enabled": use_ip_adapter,
                    },
                )

                raise AppException(
                    errors.HF_IMAGE_MODEL_LOAD_FAILED,
                    detail={
                        "provider": "hf",
                        "role": "image_generation",
                        "model_name": self._model_key,
                        "provider_type": "sdxl_lightning",
                        "error": str(exc),
                    },
                ) from exc

    # ------------------------------------------------------------
    # Text-to-image entrypoint
    # ------------------------------------------------------------
    async def generate_backgrounds(
        self,
        *,
        prompt: str,
        num_images: int,
    ) -> list[bytes]:
        """
        입력 이미지 없이 텍스트 프롬프트만으로 이미지를 생성한다.
        현재 서비스의 background generation 호환용 메서드다.
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
        """
        SDXL Lightning text-to-image 생성.
        """

        return self._generate_images_sync(
            input_image=None,
            prompt=prompt,
            negative_prompt=DEFAULT_NEGATIVE_PROMPT,
            num_images=num_images,
            size=None,
            use_ip_adapter=False,
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
        """
        기존 ImageGenerationProvider 인터페이스 구현.

        주의:
        - 기존 SD3.5 provider는 img2img/inpaint/background_swap을 사용한다.
        - 이 Provider는 입력 이미지를 IP-Adapter image condition으로 사용한다.
        - mask_image_bytes, render_mode, img2img_strength는 인터페이스 호환을 위해 받지만 직접 사용하지 않는다.
        """

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
        """
        입력 이미지를 PIL로 변환한 뒤 IP-Adapter 조건 이미지로 전달한다.
        """

        if not input_image_bytes:
            raise AppException(
                errors.IMAGE_INPUT_FILE_NOT_FOUND,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "provider_type": "sdxl_lightning",
                    "reason": "input_image_bytes_empty",
                },
            )

        # 입력 이미지 로드
        input_image = image_bytes_to_pil(input_image_bytes).convert("RGB")

        # 이미지 생성 실행
        return self._generate_images_sync(
            input_image=input_image,
            prompt=prompt,
            negative_prompt=negative_prompt or DEFAULT_NEGATIVE_PROMPT,
            num_images=num_images,
            size=size,
            use_ip_adapter=self._ip_adapter_enabled,
        )

    # ------------------------------------------------------------
    # Core inference
    # ------------------------------------------------------------
    def _generate_images_sync(
        self,
        *,
        input_image: Image.Image | None,
        prompt: str,
        negative_prompt: str | None,
        num_images: int,
        size: str | None,
        use_ip_adapter: bool,
    ) -> list[bytes]:
        """
        실제 SDXL Lightning inference를 수행한다.

        흐름:
        1. size 해석
        2. pipeline 로드 또는 캐시 재사용
        3. prompt/negative_prompt/inference setting 구성
        4. IP-Adapter 사용 시 입력 이미지 추가
        5. 이미지 생성
        6. PNG bytes 변환
        7. 성능 로그 기록
        """

        request_id = f"hf-sdxl-gen-{uuid.uuid4().hex[:10]}"

        # 생성 크기 결정
        width, height = self._parse_size(size)
        effective_num_images = max(1, int(num_images or self._num_images_per_prompt))

        # 모델 로드 또는 캐시 재사용
        pipe, load_meta = self._load_pipeline(use_ip_adapter=use_ip_adapter)

        started = time.perf_counter()

        try:
            # inference peak memory 측정 초기화
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats()

            # 생성 파라미터 구성
            kwargs: dict[str, Any] = {
                "prompt": prompt,
                "negative_prompt": negative_prompt or DEFAULT_NEGATIVE_PROMPT,
                "width": width,
                "height": height,
                "num_inference_steps": self._num_inference_steps,
                "guidance_scale": self._guidance_scale,
                "num_images_per_prompt": effective_num_images,
            }

            # IP-Adapter 입력 이미지 연결
            if use_ip_adapter and input_image is not None:
                kwargs["ip_adapter_image"] = input_image

            logger.info(
                "hf_sdxl_lightning_generation_started | model_key={} | width={} | height={} | "
                "num_images={} | ip_adapter_enabled={} | xformers_enabled={}",
                self._model_key,
                width,
                height,
                effective_num_images,
                use_ip_adapter,
                load_meta.get("xformers_enabled"),
            )

            # 이미지 생성
            with _SDXL_PIPELINE_INFERENCE_LOCK:
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
                        "provider_type": "sdxl_lightning",
                        "model_name": self._model_key,
                    },
                )

            # 결과 이미지를 PNG bytes로 변환
            output_images = [
                pil_image_to_png_bytes(image.convert("RGB").resize((width, height)))
                for image in images
            ]

            # 성능 분석용 extra 구성
            extra = {
                **load_meta,
                "width": width,
                "height": height,
                "num_images": len(output_images),
                "num_inference_steps": self._num_inference_steps,
                "guidance_scale": self._guidance_scale,
                "ip_adapter_scale": self._ip_adapter_scale if use_ip_adapter else None,
            }
            extra.update(self._torch_gpu_stats())
            extra.update(self._nvidia_smi_memory())

            # inference 성능 로그 기록
            record_performance_metric(
                pipeline="hf_sdxl_lightning",
                stage="inference",
                request_id=request_id,
                provider="hf",
                model=self._model_key,
                elapsed_ms=elapsed_ms,
                success=True,
                extra=extra,
            )

            logger.info(
                "hf_sdxl_lightning_generation_completed | model_key={} | generated_count={} | "
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
            # 이미지 생성 실패 로그 기록
            elapsed_ms = (time.perf_counter() - started) * 1000

            logger.exception(
                "hf_sdxl_lightning_generation_failed | model_key={} | error={}",
                self._model_key,
                str(exc),
            )

            record_performance_metric(
                pipeline="hf_sdxl_lightning",
                stage="inference",
                request_id=request_id,
                provider="hf",
                model=self._model_key,
                elapsed_ms=elapsed_ms,
                success=False,
                error_code="HF_SDXL_LIGHTNING_GENERATION_FAILED",
                error_type=exc.__class__.__name__,
                extra={
                    "provider_type": "sdxl_lightning",
                    "width": width,
                    "height": height,
                    "ip_adapter_enabled": use_ip_adapter,
                    "xformers_enabled": load_meta.get("xformers_enabled"),
                },
            )

            raise AppException(
                errors.HF_IMAGE_GENERATION_FAILED,
                detail={
                    "provider": "hf",
                    "role": "image_generation",
                    "model_name": self._model_key,
                    "provider_type": "sdxl_lightning",
                    "error": str(exc),
                },
            ) from exc
