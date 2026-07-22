import asyncio

import pytest
from PIL import Image

from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.schemas.image_ad import ImageAdRequest
from app.services.pipelines import image_pipeline
from app.services.pipelines.image_pipeline import generate_image_ads
from app.utils.image_bytes import (
    decode_base64_to_image_bytes,
    pil_image_to_png_bytes,
)


class FakeImageProvider:
    def __init__(self):
        self.calls = []

    async def generate(
        self,
        *,
        input_image_bytes: bytes,
        prompt: str,
        num_images: int,
        mask_image_bytes: bytes | None = None,
        size: str | None = None,
        render_mode: str | None = None,
        negative_prompt: str | None = None,
        img2img_strength: float | None = None,
    ) -> list[bytes]:
        self.calls.append(
            {
                "input_bytes_len": len(input_image_bytes),
                "prompt": prompt,
                "num_images": num_images,
                "has_mask": bool(mask_image_bytes),
            }
        )

        image = Image.new("RGB", (16, 16), "white")
        return [pil_image_to_png_bytes(image) for _ in range(num_images)]


def _sample_source_bytes() -> bytes:
    image = Image.new("RGBA", (16, 16), (255, 255, 255, 255))
    return pil_image_to_png_bytes(image)


def test_generate_image_ads_returns_base64_without_file_path(monkeypatch):
    fake_provider = FakeImageProvider()
    monkeypatch.setattr(image_pipeline, "get_image_provider", lambda: fake_provider)
    monkeypatch.setattr(image_pipeline, "get_provider_name", lambda role: "openai")
    monkeypatch.setattr(
        image_pipeline,
        "get_variant_image_size",
        lambda variant: "1024x1536",
    )

    payload = ImageAdRequest(
        store_name="만월",
        menu_name="데몬헌터스 케이크",
        food_type="bread_dessert",
        num_images=3,
        generation_mode="direct_poster",
    )

    result = asyncio.run(
        generate_image_ads(
            payload=payload,
            source_image_bytes=_sample_source_bytes(),
        )
    )

    assert result.request_id.startswith("img-")
    assert result.generation_mode == "direct_poster"
    assert len(result.images) == 3
    assert len(result.poster_images) == 3
    assert len(result.image_bytes_list) == 3
    assert result.composite_images == []

    decoded = decode_base64_to_image_bytes(result.images[0])
    assert decoded == result.image_bytes_list[0]

    assert len(fake_provider.calls) == 3


def test_generate_image_ads_cancels_remaining_variant_tasks_on_failure(monkeypatch):
    started = 0
    cancelled = 0
    never_finishes = asyncio.Event()

    async def fake_generate_poster_with_retries(**kwargs):
        nonlocal started, cancelled
        started += 1

        if started == 1:
            await asyncio.sleep(0)
            raise RuntimeError("first variant failed")

        try:
            await never_finishes.wait()
        except asyncio.CancelledError:
            cancelled += 1
            raise

    monkeypatch.setattr(image_pipeline, "get_image_provider", lambda: object())
    monkeypatch.setattr(image_pipeline, "get_provider_name", lambda role: "openai")
    monkeypatch.setattr(
        image_pipeline,
        "get_variant_image_size",
        lambda variant: "1024x1536",
    )
    monkeypatch.setattr(
        image_pipeline,
        "_generate_poster_with_retries",
        fake_generate_poster_with_retries,
    )

    payload = ImageAdRequest(
        store_name="만월",
        menu_name="데몬헌터스 케이크",
        food_type="bread_dessert",
        num_images=3,
        generation_mode="direct_poster",
    )

    with pytest.raises(AppException):
        asyncio.run(
            generate_image_ads(
                payload=payload,
                source_image_bytes=_sample_source_bytes(),
            )
        )

    assert started == 3
    assert cancelled == 2


def test_poster_generation_does_not_retry_provider_exception(monkeypatch):
    monkeypatch.setattr(image_pipeline, "record_registry_metric", lambda *args, **kwargs: None)

    class FailingProvider:
        def __init__(self):
            self.calls = 0

        async def generate(self, **kwargs):
            self.calls += 1
            raise AppException(errors.OPENAI_AUTHENTICATION_FAILED)

    provider = FailingProvider()

    with pytest.raises(AppException) as exc_info:
        asyncio.run(
            image_pipeline._generate_poster_with_retries(
                provider=provider,
                source_image_bytes=_sample_source_bytes(),
                base_prompt="poster prompt",
                request_id="gen-retry-test",
                variant="poster",
            )
        )

    assert exc_info.value.code == "OPENAI_AUTHENTICATION_FAILED"
    assert provider.calls == 1


def test_poster_generation_retries_only_empty_results(monkeypatch):
    monkeypatch.setattr(image_pipeline, "record_registry_metric", lambda *args, **kwargs: None)

    class EmptyProvider:
        def __init__(self):
            self.calls = 0

        async def generate(self, **kwargs):
            self.calls += 1
            return []

    provider = EmptyProvider()

    with pytest.raises(AppException) as exc_info:
        asyncio.run(
            image_pipeline._generate_poster_with_retries(
                provider=provider,
                source_image_bytes=_sample_source_bytes(),
                base_prompt="poster prompt",
                request_id="gen-retry-test",
                variant="poster",
            )
        )

    assert exc_info.value.code == "IMAGE_POSTER_RETRY_FAILED"
    assert provider.calls == len(image_pipeline.POSTER_EMPTY_RESULT_RETRY_SUFFIXES)
