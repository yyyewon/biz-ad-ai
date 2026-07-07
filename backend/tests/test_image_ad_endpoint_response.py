from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.schemas.image_ad import ImageAdResponse
from app.utils.image_bytes import encode_image_bytes_to_base64, pil_image_to_png_bytes


client = TestClient(app)


def _sample_png_base64(color: str = "white") -> str:
    image = Image.new("RGB", (16, 16), color)
    return encode_image_bytes_to_base64(pil_image_to_png_bytes(image))


def test_image_ad_endpoint_returns_common_success_response(monkeypatch):
    from app.api.v1.endpoints import image_ad as image_ad_endpoint

    input_b64 = _sample_png_base64("white")
    output_b64 = _sample_png_base64("green")

    calls = {}

    def fake_generate_image_ads(*, payload, source_image_bytes, seed=None):
        calls["payload"] = payload
        calls["source_image_bytes_len"] = len(source_image_bytes)

        return ImageAdResponse(
            request_id="img-test",
            mood=payload.mood,
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
            applied_moods=[payload.mood],
        )

    monkeypatch.setattr(
        image_ad_endpoint,
        "generate_image_ads",
        fake_generate_image_ads,
    )

    response = client.post(
        "/api/v1/ad/image",
        json={
            "input_image_base64": input_b64,
            "store_name": "만월",
            "menu_name": "데몬헌터스 케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

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


def test_image_ad_endpoint_requires_input_image_base64():
    response = client.post(
        "/api/v1/ad/image",
        json={
            "store_name": "만월",
            "menu_name": "데몬헌터스 케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

    body = response.json()

    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "EMPTY_IMAGE_FILE"
