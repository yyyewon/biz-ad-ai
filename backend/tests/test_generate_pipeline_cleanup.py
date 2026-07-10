import asyncio

from PIL import Image

from app.schemas.image_ad import ImageAdResponse
from app.services.pipelines import generate_pipeline
from app.services.pipelines.generate_pipeline import run_generate_pipeline
from app.utils.image_bytes import encode_image_bytes_to_base64, pil_image_to_png_bytes


def _sample_png_bytes(color: str = "white") -> bytes:
    image = Image.new("RGB", (16, 16), color)
    return pil_image_to_png_bytes(image)


def test_generate_pipeline_does_not_pass_output_path_arguments(monkeypatch):
    source_bytes = _sample_png_bytes("white")
    poster_bytes = _sample_png_bytes("green")
    poster_b64 = encode_image_bytes_to_base64(poster_bytes)

    captured_kwargs = {}

    async def fake_run_text_pipeline(**kwargs):
        return "생성된 광고 문구"

    monkeypatch.setattr(
        generate_pipeline,
        "run_text_pipeline",
        fake_run_text_pipeline,
    )

    async def fake_generate_image_ads(**kwargs):
        captured_kwargs.update(kwargs)

        payload = kwargs["payload"]

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
    assert result["image_generation_success"] is True
    assert len(result["images"]) == 3

    assert "payload" in captured_kwargs
    assert "source_image_bytes" in captured_kwargs
    assert captured_kwargs["source_image_bytes"] == source_bytes

    assert "output_root" not in captured_kwargs
    assert "public_prefix" not in captured_kwargs
    assert "output_dir" not in captured_kwargs


def test_generate_pipeline_fallback_does_not_create_file_path_response(monkeypatch):
    source_bytes = _sample_png_bytes("white")

    async def fake_run_text_pipeline(**kwargs):
        return "생성된 광고 문구"

    monkeypatch.setattr(
        generate_pipeline,
        "run_text_pipeline",
        fake_run_text_pipeline,
    )

    async def fake_generate_image_ads(**kwargs):
        raise RuntimeError("image generation failed")

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
    assert len(result["images"]) == 3

    assert "image_path" not in result
    assert "download_url" not in result
    assert "poster_images" not in result
