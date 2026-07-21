from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.api.v1.endpoints import dev_apis
from app.core.deps import get_current_user
from app.schemas.image_ad import ImageAdResponse
from app.utils.image_bytes import encode_image_bytes_to_base64, pil_image_to_png_bytes


client = TestClient(app)


def _override_login(user_id: int = 123) -> None:
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id}


def _sample_png_base64(color: str = "white") -> str:
    image = Image.new("RGB", (16, 16), color)
    return encode_image_bytes_to_base64(pil_image_to_png_bytes(image))


def test_image_ad_endpoint_returns_common_success_response(monkeypatch):
    input_b64 = _sample_png_base64("white")
    output_b64 = _sample_png_base64("green")

    calls = {}

    async def fake_check_and_increment_daily_usage(user_id: int):
        calls["quota_user_id"] = user_id

    async def fake_generate_image_ads(*, payload, source_image_bytes, seed=None):
        calls["payload"] = payload
        calls["source_image_bytes_len"] = len(source_image_bytes)

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
            images=[output_b64],
            poster_images=[output_b64],
        )

    monkeypatch.setattr(dev_apis, "generate_image_ads", fake_generate_image_ads)
    monkeypatch.setattr(
        dev_apis,
        "check_and_increment_daily_usage_async",
        fake_check_and_increment_daily_usage,
    )
    _override_login()

    try:
        response = client.post(
            "/api/v1/dev/ad/image",
            json={
                "input_image_base64": input_b64,
                "store_name": "만월",
                "menu_name": "데몬헌터스 케이크",
                "food_type": "bread_dessert",
                "num_images": 1,
                "generation_mode": "direct_poster",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["request_id"] == "img-test"
    assert body["data"]["images"] == [output_b64]
    assert body["data"]["poster_images"] == [output_b64]

    assert calls["payload"].input_image_base64 == input_b64
    assert calls["payload"].input_image_path is None
    assert calls["payload"].image_path is None
    assert calls["source_image_bytes_len"] > 0
    assert calls["quota_user_id"] == 123


def test_image_ad_endpoint_requires_input_image_base64():
    _override_login()

    try:
        response = client.post(
            "/api/v1/dev/ad/image",
            json={
                "store_name": "만월",
                "menu_name": "데몬헌터스 케이크",
                "food_type": "bread_dessert",
                "num_images": 1,
                "generation_mode": "direct_poster",
            },
        )
    finally:
        app.dependency_overrides.clear()

    body = response.json()

    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "EMPTY_IMAGE_FILE"
