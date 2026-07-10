import asyncio

from PIL import Image

from app.schemas.image_ad import ImageAdResponse
from app.services.pipelines import generate_pipeline
from app.services.pipelines.generate_pipeline import run_generate_pipeline
from app.utils.image_bytes import (
    decode_base64_to_image_bytes,
    encode_image_bytes_to_base64,
    pil_image_to_png_bytes,
)


def _sample_png_bytes(color: str = "white") -> bytes:
    image = Image.new("RGB", (16, 16), color)
    return pil_image_to_png_bytes(image)


def test_run_generate_pipeline_without_image(monkeypatch):
    async def fake_run_text_pipeline(**kwargs):
        return "생성된 광고 문구"

    monkeypatch.setattr(
        generate_pipeline,
        "run_text_pipeline",
        fake_run_text_pipeline,
    )

    result = asyncio.run(
        run_generate_pipeline(
            store_name="만월",
            menu_name="데몬헌터스 케이크",
            purpose="신메뉴 홍보",
            food="",
            llm_request="",
            image_request="",
            tone="감성적인",
            image_bytes=None,
        )
    )

    assert result["caption"] == "생성된 광고 문구"
    assert result["images"] == []
    assert result["partial_success"] is False
    assert result["warnings"] == []
    assert result["image_generation_success"] is None


def test_run_generate_pipeline_with_image_uses_memory_bytes(monkeypatch):
    source_bytes = _sample_png_bytes("white")
    poster_bytes = _sample_png_bytes("green")
    poster_b64 = encode_image_bytes_to_base64(poster_bytes)

    calls = {}

    async def fake_run_text_pipeline(**kwargs):
        return "생성된 광고 문구"

    async def fake_generate_image_ads(*, payload, source_image_bytes, seed=None):
        calls["image_payload"] = payload
        calls["source_image_bytes"] = source_image_bytes

        return ImageAdResponse(
            request_id="img-test",
            prompt_used="poster prompt",
            num_images=1,
            latency_ms=100,
            generation_mode=payload.generation_mode,
            stage_latencies_ms={
                "food_generation_ms": 0,
                "poster_generation_ms": 100,
                "total_ms": 100,
            },
            images=[poster_b64],
            poster_images=[poster_b64],
            image_bytes_list=[poster_bytes],
            applied_variants=["studio"],
            food_type="rice_dish",
        )

    monkeypatch.setattr(
        generate_pipeline,
        "run_text_pipeline",
        fake_run_text_pipeline,
    )
    monkeypatch.setattr(
        generate_pipeline,
        "generate_image_ads",
        fake_generate_image_ads,
    )

    result = asyncio.run(
        run_generate_pipeline(
            store_name="만월",
            menu_name="데몬헌터스 케이크",
            purpose="신메뉴 홍보",
            food="덮밥, 볶음, 비빔",
            llm_request="캐릭터 컨셉",
            image_request="따뜻한 배경",
            tone="감성적인",
            image_bytes=source_bytes,
        )
    )

    assert calls["source_image_bytes"] == source_bytes

    image_payload = calls["image_payload"]
    assert image_payload.input_image_path is None
    assert image_payload.image_path is None
    assert image_payload.store_name == "만월"
    assert image_payload.menu_name == "데몬헌터스 케이크"
    assert image_payload.food_type == "rice_dish"
    assert image_payload.extra_notes == "따뜻한 배경"

    assert result["caption"] == "생성된 광고 문구"
    assert result["partial_success"] is False
    assert result["warnings"] == []
    assert result["image_generation_success"] is True

    assert len(result["images"]) == 3
    assert result["images"][0] == poster_b64
    assert decode_base64_to_image_bytes(result["images"][0]) == poster_bytes

    assert result["image_generation"]["request_id"] == "img-test"
    assert result["image_generation"]["poster_image_count"] == 1
    assert result["image_generation"]["food_type"] == "rice_dish"


def test_run_generate_pipeline_image_failure_returns_fallback(monkeypatch):
    source_bytes = _sample_png_bytes("white")

    async def fake_run_text_pipeline(**kwargs):
        return "생성된 광고 문구"

    async def fake_generate_image_ads(*, payload, source_image_bytes, seed=None):
        raise RuntimeError("image generation failed")

    monkeypatch.setattr(
        generate_pipeline,
        "run_text_pipeline",
        fake_run_text_pipeline,
    )
    monkeypatch.setattr(
        generate_pipeline,
        "generate_image_ads",
        fake_generate_image_ads,
    )

    result = asyncio.run(
        run_generate_pipeline(
            store_name="만월",
            menu_name="데몬헌터스 케이크",
            purpose="신메뉴 홍보",
            food="덮밥, 볶음, 비빔",
            llm_request="",
            image_request="",
            tone="감성적인",
            image_bytes=source_bytes,
        )
    )

    assert result["caption"] == "생성된 광고 문구"
    assert result["partial_success"] is True
    assert result["image_generation_success"] is False
    assert len(result["warnings"]) == 1
    assert len(result["images"]) == 3

    assert decode_base64_to_image_bytes(result["images"][0]) == source_bytes
