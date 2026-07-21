import asyncio

import pytest
from PIL import Image

from app.core.exceptions import AppException
from app.schemas.image_ad import ImageAdResponse
from app.services.pipelines import generate_pipeline
from app.services.pipelines.generate_pipeline import run_generate_pipeline
from app.utils.image_bytes import encode_image_bytes_to_base64, pil_image_to_png_bytes


def _sample_png_bytes(color: str = "white") -> bytes:
    image = Image.new("RGB", (16, 16), color)
    return pil_image_to_png_bytes(image)


@pytest.mark.parametrize("with_image", [False, True])
def test_text_failure_emits_failed_without_done(monkeypatch, with_image):
    source_bytes = _sample_png_bytes("white") if with_image else None
    poster_bytes = _sample_png_bytes("green")
    poster_b64 = encode_image_bytes_to_base64(poster_bytes)
    events: list[dict] = []

    async def fake_run_text_pipeline(**kwargs):
        raise RuntimeError("text generation failed")

    async def fake_generate_image_ads(**kwargs):
        payload = kwargs["payload"]
        return ImageAdResponse(
            request_id="img-test",
            prompt_used="poster prompt",
            num_images=1,
            latency_ms=100,
            generation_mode=payload.generation_mode,
            stage_latencies_ms={},
            images=[poster_b64],
            poster_images=[poster_b64],
            image_bytes_list=[poster_bytes],
            applied_variants=["studio"],
        )

    async def on_progress(event: dict):
        events.append(event)

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

    with pytest.raises(AppException):
        asyncio.run(
            run_generate_pipeline(
                store_name="만월",
                menu_name="데몬헌터스 케이크",
                purpose="신메뉴 홍보",
                food="덮밥, 볶음, 비빔" if with_image else "",
                llm_request="",
                image_request="",
                tone="감성적인",
                image_bytes=source_bytes,
                on_progress=on_progress,
            )
        )

    text_statuses = [
        event["status"]
        for event in events
        if event.get("event") == "stage" and event.get("track") == "text"
    ]
    assert text_statuses == ["start", "failed"]


def test_image_stage_cancellation_cleans_up_parallel_text_task(monkeypatch):
    text_started = asyncio.Event()
    text_cancelled = False

    async def fake_run_text_pipeline(**kwargs):
        nonlocal text_cancelled
        text_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            text_cancelled = True
            raise

    async def fake_generate_image_ads(**kwargs):
        await text_started.wait()
        raise asyncio.CancelledError

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

    async def run_test():
        with pytest.raises(asyncio.CancelledError):
            await run_generate_pipeline(
                store_name="만월",
                menu_name="데몬헌터스 케이크",
                purpose="신메뉴 홍보",
                food="덮밥, 볶음, 비빔",
                llm_request="",
                image_request="",
                tone="감성적인",
                image_bytes=_sample_png_bytes(),
            )

    asyncio.run(run_test())

    assert text_cancelled is True
