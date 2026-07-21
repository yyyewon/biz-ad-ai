import asyncio
from types import SimpleNamespace

import httpx
import pytest
from openai import AuthenticationError

from app.core.exceptions import AppException
from app.services.providers.openai_image_provider import OpenAIImageProvider
from app.services.providers.openai_text_provider import OpenAITextProvider
from app.utils.image_bytes import pil_image_to_png_bytes
from PIL import Image


def _authentication_error() -> AuthenticationError:
    response = httpx.Response(
        401,
        request=httpx.Request("POST", "https://api.openai.com/v1/test"),
    )
    return AuthenticationError(
        "invalid api key",
        response=response,
        body={"error": {"code": "invalid_api_key"}},
    )


@pytest.mark.parametrize(
    "provider_factory",
    [
        lambda: OpenAITextProvider(api_key="sk-test-ㄱ"),
        lambda: OpenAIImageProvider(api_key="sk-test-ㄱ"),
    ],
)
def test_openai_provider_rejects_non_ascii_api_key_before_request(provider_factory):
    with pytest.raises(AppException) as exc_info:
        provider_factory()

    assert exc_info.value.code == "OPENAI_AUTHENTICATION_FAILED"
    assert exc_info.value.detail["reason"] == "api_key_must_be_ascii"


def test_openai_text_provider_maps_authentication_error():
    class FailingResponses:
        async def create(self, **kwargs):
            raise _authentication_error()

    provider = OpenAITextProvider(
        api_key="sk-test-key",
        model_settings={"api_type": "responses"},
    )
    provider.client = SimpleNamespace(responses=FailingResponses())

    with pytest.raises(AppException) as exc_info:
        asyncio.run(
            provider.generate_text(
                prompt="test prompt",
                system_instruction="test instruction",
            )
        )

    assert exc_info.value.code == "OPENAI_AUTHENTICATION_FAILED"
    assert exc_info.value.detail["status_code"] == 401


def test_openai_image_provider_maps_authentication_error():
    class FailingImages:
        async def edit(self, **kwargs):
            raise _authentication_error()

    provider = OpenAIImageProvider(api_key="sk-test-key")
    provider._client = SimpleNamespace(images=FailingImages())
    source = pil_image_to_png_bytes(Image.new("RGB", (16, 16), "white"))

    with pytest.raises(AppException) as exc_info:
        asyncio.run(
            provider.generate(
                input_image_bytes=source,
                prompt="test prompt",
                num_images=1,
            )
        )

    assert exc_info.value.code == "OPENAI_AUTHENTICATION_FAILED"
    assert exc_info.value.detail["status_code"] == 401
