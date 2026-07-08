import asyncio

from PIL import Image

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

    payload = ImageAdRequest(
        store_name="만월",
        menu_name="데몬헌터스 케이크",
        mood="cozy",
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
    assert all(call["has_mask"] for call in fake_provider.calls)


def test_generate_image_ads_two_stage_uses_food_then_poster(monkeypatch):
    fake_provider = FakeImageProvider()
    monkeypatch.setattr(image_pipeline, "get_image_provider", lambda: fake_provider)

    payload = ImageAdRequest(
        store_name="만월",
        menu_name="데몬헌터스 케이크",
        mood="cozy",
        mood_list=["cozy", "fresh"],
        num_images=2,
        generation_mode="two_stage",
    )

    result = asyncio.run(
        generate_image_ads(
            payload=payload,
            source_image_bytes=_sample_source_bytes(),
        )
    )

    assert result.generation_mode == "two_stage"
    assert len(result.images) == 2
    assert len(result.composite_images) == 2
    assert len(result.image_bytes_list) == 2
    assert result.applied_moods == ["cozy", "fresh"]

    # two_stage:
    # - food_generation 2회
    # - poster_generation 2회
    assert len(fake_provider.calls) == 4

    food_calls = fake_provider.calls[:2]
    poster_calls = fake_provider.calls[2:]

    assert all(call["has_mask"] for call in food_calls)
    assert all(not call["has_mask"] for call in poster_calls)
