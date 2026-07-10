import asyncio
from types import SimpleNamespace

from PIL import Image

from app.services.providers import openai_image_provider
from app.services.providers.openai_image_provider import OpenAIImageProvider
from app.utils.image_bytes import encode_image_bytes_to_base64, pil_image_to_png_bytes


class FakeImagesClient:
    def __init__(self, image_bytes: bytes):
        self.image_bytes = image_bytes
        self.edit_calls = []
        self.generate_calls = []

    async def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        return SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json=encode_image_bytes_to_base64(self.image_bytes),
                )
            ]
        )

    async def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json=encode_image_bytes_to_base64(self.image_bytes),
                )
            ]
        )


class FakeAsyncOpenAI:
    images_client: FakeImagesClient | None = None

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.images = self.__class__.images_client


def _sample_png_bytes() -> bytes:
    image = Image.new("RGB", (16, 16), "white")
    return pil_image_to_png_bytes(image)


def test_openai_image_provider_generate_returns_bytes(monkeypatch):
    image_bytes = _sample_png_bytes()
    fake_images_client = FakeImagesClient(image_bytes=image_bytes)

    FakeAsyncOpenAI.images_client = fake_images_client
    monkeypatch.setattr(openai_image_provider, "AsyncOpenAI", FakeAsyncOpenAI)

    provider = OpenAIImageProvider(api_key="test-api-key")

    result = asyncio.run(
        provider.generate(
            input_image_bytes=image_bytes,
            mask_image_bytes=None,
            prompt="테스트 프롬프트",
            num_images=2,
        )
    )

    assert result == [image_bytes, image_bytes]
    assert len(fake_images_client.edit_calls) == 2
    assert fake_images_client.edit_calls[0]["image"].name == "source_1.png"
    assert fake_images_client.edit_calls[0]["model"] == provider.model_name


def test_openai_image_provider_generate_with_mask(monkeypatch):
    image_bytes = _sample_png_bytes()
    mask_bytes = _sample_png_bytes()
    fake_images_client = FakeImagesClient(image_bytes=image_bytes)

    FakeAsyncOpenAI.images_client = fake_images_client
    monkeypatch.setattr(openai_image_provider, "AsyncOpenAI", FakeAsyncOpenAI)

    provider = OpenAIImageProvider(api_key="test-api-key")

    result = asyncio.run(
        provider.generate(
            input_image_bytes=image_bytes,
            mask_image_bytes=mask_bytes,
            prompt="테스트 프롬프트",
            num_images=1,
        )
    )

    assert result == [image_bytes]
    assert len(fake_images_client.edit_calls) == 1
    assert fake_images_client.edit_calls[0]["image"].name == "source_1.png"
    assert fake_images_client.edit_calls[0]["mask"].name == "mask_1.png"


def test_openai_image_provider_generate_backgrounds_returns_bytes(monkeypatch):
    image_bytes = _sample_png_bytes()
    fake_images_client = FakeImagesClient(image_bytes=image_bytes)

    FakeAsyncOpenAI.images_client = fake_images_client
    monkeypatch.setattr(openai_image_provider, "AsyncOpenAI", FakeAsyncOpenAI)

    provider = OpenAIImageProvider(api_key="test-api-key")

    result = asyncio.run(
        provider.generate_backgrounds(
            prompt="배경 생성 프롬프트",
            num_images=2,
        )
    )

    assert result == [image_bytes, image_bytes]
    assert len(fake_images_client.generate_calls) == 2
    assert fake_images_client.generate_calls[0]["model"] == provider.model_name
