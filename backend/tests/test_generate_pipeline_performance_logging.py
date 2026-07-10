from contextlib import contextmanager
import asyncio

from PIL import Image

from app.schemas.image_ad import ImageAdResponse
from app.services.pipelines import generate_pipeline
from app.services.pipelines.generate_pipeline import run_generate_pipeline
from app.utils.image_bytes import encode_image_bytes_to_base64, pil_image_to_png_bytes


def _sample_png_bytes(color: str = "white") -> bytes:
    image = Image.new("RGB", (16, 16), color)
    return pil_image_to_png_bytes(image)


def test_generate_pipeline_records_memory_based_stage_metrics(monkeypatch):
    """
    메모리 기반 image_pipeline으로 바뀐 뒤에도
    단계별 성능 로그 stage가 유지되는지 확인한다.
    """

    source_bytes = _sample_png_bytes("white")
    processed_bytes = _sample_png_bytes("blue")
    poster_bytes = _sample_png_bytes("green")
    poster_b64 = encode_image_bytes_to_base64(poster_bytes)

    metric_calls: list[dict] = []

    @contextmanager
    def fake_measure_stage(**kwargs):
        metric_calls.append(
            {
                "source": "measure_stage",
                "stage": kwargs["stage"],
                "provider": kwargs["provider"],
                "model": kwargs["model"],
                "request_id": kwargs["request_id"],
            }
        )
        yield

    def fake_record_performance_metric(**kwargs):
        metric_calls.append(
            {
                "source": "record_performance_metric",
                **kwargs,
            }
        )

    monkeypatch.setattr(generate_pipeline, "measure_stage", fake_measure_stage)
    monkeypatch.setattr(
        generate_pipeline,
        "record_performance_metric",
        fake_record_performance_metric,
    )

    async def fake_run_text_pipeline(**kwargs):
        return "생성된 광고 문구"

    monkeypatch.setattr(
        generate_pipeline,
        "run_text_pipeline",
        fake_run_text_pipeline,
    )

    monkeypatch.setattr(
        generate_pipeline,
        "remove_background_and_resize",
        lambda image_bytes: processed_bytes,
    )

    async def fake_generate_image_ads(*, payload, source_image_bytes, seed=None):
        assert source_image_bytes == processed_bytes

        return ImageAdResponse(
            request_id="img-test",
            mood=payload.mood,
            prompt_used="poster prompt",
            num_images=1,
            latency_ms=130,
            generation_mode=payload.generation_mode,
            stage_latencies_ms={
                "food_generation_ms": 0,
                "poster_generation_ms": 120,
                "total_ms": 130,
            },
            images=[poster_b64],
            poster_images=[poster_b64],
            image_bytes_list=[poster_bytes],
            applied_moods=[payload.mood],
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
            request_note="",
            moods=["cozy"],
            tone="감성적인",
            image_bytes=source_bytes,
        )
    )

    assert result["image_generation_success"] is True

    stages = [call["stage"] for call in metric_calls]

    assert "text_generation" in stages
    assert "image_preprocess" in stages
    assert "image_generation" in stages
    assert "food_generation" in stages
    assert "poster_generation" in stages
    assert "image_pipeline_total" in stages
    assert "total_pipeline" in stages

    total_pipeline_calls = [
        call
        for call in metric_calls
        if call["stage"] == "total_pipeline"
    ]

    assert total_pipeline_calls
    assert total_pipeline_calls[-1]["success"] is True
    assert total_pipeline_calls[-1]["extra"]["partial_success"] is False


def test_generate_pipeline_records_partial_success_total_metric(monkeypatch):
    """
    이미지 생성 실패 후 fallback으로 응답하는 경우
    total_pipeline은 success=false, partial_success=true로 기록한다.
    """

    source_bytes = _sample_png_bytes("white")
    processed_bytes = _sample_png_bytes("blue")

    metric_calls: list[dict] = []

    @contextmanager
    def fake_measure_stage(**kwargs):
        metric_calls.append(
            {
                "source": "measure_stage",
                "stage": kwargs["stage"],
                "provider": kwargs["provider"],
                "model": kwargs["model"],
                "request_id": kwargs["request_id"],
            }
        )
        yield

    def fake_record_performance_metric(**kwargs):
        metric_calls.append(
            {
                "source": "record_performance_metric",
                **kwargs,
            }
        )

    monkeypatch.setattr(generate_pipeline, "measure_stage", fake_measure_stage)
    monkeypatch.setattr(
        generate_pipeline,
        "record_performance_metric",
        fake_record_performance_metric,
    )

    async def fake_run_text_pipeline(**kwargs):
        return "생성된 광고 문구"

    monkeypatch.setattr(
        generate_pipeline,
        "run_text_pipeline",
        fake_run_text_pipeline,
    )

    monkeypatch.setattr(
        generate_pipeline,
        "remove_background_and_resize",
        lambda image_bytes: processed_bytes,
    )

    async def fake_generate_image_ads(*, payload, source_image_bytes, seed=None):
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
            request_note="",
            moods=["cozy"],
            tone="감성적인",
            image_bytes=source_bytes,
        )
    )

    assert result["partial_success"] is True
    assert result["image_generation_success"] is False

    total_pipeline_calls = [
        call
        for call in metric_calls
        if call["stage"] == "total_pipeline"
    ]

    assert total_pipeline_calls
    assert total_pipeline_calls[-1]["success"] is False
    assert total_pipeline_calls[-1]["extra"]["partial_success"] is True
    assert total_pipeline_calls[-1]["error_code"] == "UNHANDLED_EXCEPTION"
    assert total_pipeline_calls[-1]["error_type"] == "RuntimeError"
