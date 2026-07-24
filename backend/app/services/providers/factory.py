"""
Provider factory.

역할:
- backend/config/model.yaml의 active_profile을 기준으로 provider를 선택한다.
- text_generation_provider와 image_generation_provider를 분리한다.
"""

from __future__ import annotations

from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.core.model_config import get_model_settings, get_provider_name
from app.services.providers.base import ImageGenerationProvider, TextGenerationProvider


def get_text_provider() -> TextGenerationProvider:
    """
    active_profile 기준 텍스트 생성 provider를 반환한다.
    """

    provider_name = get_provider_name("text_generation")

    if provider_name == "openai":
        from app.services.providers.openai_text_provider import OpenAITextProvider

        resolved = get_model_settings(
            role="text_generation",
            provider_name="openai",
        )

        return OpenAITextProvider(
            model_name=resolved["model_name"],
            model_settings=resolved["settings"],
        )

    if provider_name == "hf":
        raise AppException(
            errors.HF_PROVIDER_NOT_AVAILABLE,
            detail={
                "role": "text_generation",
                "message": "HF Text Provider는 Step 10에서 구현 예정입니다.",
            },
        )

    raise AppException(
        errors.PROVIDER_NOT_SUPPORTED,
        detail={
            "role": "text_generation",
            "provider": provider_name,
            "supported_providers": ["openai", "hf"],
        },
    )


def get_image_provider() -> ImageGenerationProvider:
    """
    active_profile 기준 이미지 생성 provider를 반환한다.
    """

    provider_name = get_provider_name("image_generation")

    if provider_name == "openai":
        from app.services.providers.openai_image_provider import OpenAIImageProvider

        resolved = get_model_settings(
            role="image_generation",
            provider_name="openai",
        )
        model_settings = resolved["settings"]

        return OpenAIImageProvider(
            model=resolved["model_name"],
            size=model_settings.get("size"),
            quality=model_settings.get("quality"),
            output_format=model_settings.get("output_format"),
            model_settings=model_settings,
        )

    if provider_name == "hf":
        # ------------------------------------------------------------
        # HF 이미지 Provider 선택
        # ------------------------------------------------------------
        # model.yaml의 active_profile과 default_model을 기준으로 HF 모델 설정을 가져온다.
        resolved = get_model_settings(
            role="image_generation",
            provider_name="hf",
        )

        model_settings = resolved["settings"]

        # ------------------------------------------------------------
        # HF Provider 세부 타입 분기
        # ------------------------------------------------------------
        provider_type = str(model_settings.get("provider_type", "sd3")).lower()

        if provider_type == "sdxl_ip_adapter":
            from app.services.providers.hf_sdxl_ip_adapter_provider import (
                HFSDXLIPAdapterImageProvider,
            )

            return HFSDXLIPAdapterImageProvider(
                model_name=resolved["model_name"],
                model_settings=model_settings,
            )

        if provider_type == "sdxl_lightning":
            from app.services.providers.hf_sdxl_lightning_provider import (
                HFSDXLLightningImageProvider,
            )

            return HFSDXLLightningImageProvider(
                model_name=resolved["model_name"],
                model_settings=model_settings,
            )

        if provider_type == "sd15_controlnet_tile":
            from app.services.providers.hf_sd15_controlnet_tile_provider import (
                HFSD15ControlNetTileImageProvider,
            )

            return HFSD15ControlNetTileImageProvider(
                model_name=resolved["model_name"],
                model_settings=model_settings,
            )

        from app.services.providers.hf_image_provider import HFImageProvider

        return HFImageProvider(
            model_name=resolved["model_name"],
            model_settings=model_settings,
        )

    raise AppException(
        errors.PROVIDER_NOT_SUPPORTED,
        detail={
            "role": "image_generation",
            "provider": provider_name,
            "supported_providers": ["openai", "hf"],
        },
    )
