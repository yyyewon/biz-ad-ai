"""
Provider factory.

역할:
- backend/config/model.yaml의 active_profile을 기준으로 provider를 선택한다.
- text_generation_provider와 image_generation_provider를 분리한다.
"""

from __future__ import annotations

from app.core import error_constants as errors
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.model_config import get_model_settings, get_provider_name
from app.services.providers.openai_image_provider import OpenAIImageProvider
from app.services.providers.openai_text_provider import OpenAITextProvider
from app.services.providers.hf_image_provider import HFImageProvider
from app.services.providers.hf_text_provider import HFTextProvider


def get_text_provider() -> OpenAITextProvider:
    """
    active_profile 기준 텍스트 생성 provider를 반환한다.
    """

    provider_name = get_provider_name("text_generation")

    if provider_name == "openai":
        resolved = get_model_settings(
            role="text_generation",
            provider_name="openai",
        )

        return OpenAITextProvider(
            model_name=resolved["model_name"],
            model_settings=resolved["settings"],
        )

    if provider_name == "hf":
        resolved = get_model_settings(
            role="text_generation",
            provider_name="hf",
        )
        return HFTextProvider(
            model_name=resolved["model_name"],
            model_settings=resolved["settings"],
        )

    raise AppException(
        errors.PROVIDER_NOT_SUPPORTED,
        detail={
            "role": "text_generation",
            "provider": provider_name,
            "supported_providers": ["openai", "hf"],
        },
    )


def get_image_provider() -> OpenAIImageProvider:
    """
    active_profile 기준 이미지 생성 provider를 반환한다.
    """

    provider_name = get_provider_name("image_generation")

    if provider_name == "openai":
        settings = get_settings()

        resolved = get_model_settings(
            role="image_generation",
            provider_name="openai",
        )
        model_settings = resolved["settings"]

        return OpenAIImageProvider(
            api_key=settings.openai_api_key,
            model=resolved["model_name"],
            size=model_settings.get("size"),
            quality=model_settings.get("quality"),
            output_format=model_settings.get("output_format"),
            model_settings=model_settings,
        )

    if provider_name == "hf":
        resolved = get_model_settings(
            role="text_generation",
            provider_name="hf",
        )
        return HFTextProvider(
            model_name=resolved["model_name"],
            model_settings=resolved["settings"],
        )

    raise AppException(
        errors.PROVIDER_NOT_SUPPORTED,
        detail={
            "role": "image_generation",
            "provider": provider_name,
            "supported_providers": ["openai", "hf"],
        },
    )
