from __future__ import annotations

import base64
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.utils.image_bytes import encode_image_bytes_to_base64, pil_image_to_png_bytes

client = TestClient(app)


def _png_bytes() -> bytes:
    image = Image.new("RGB", (16, 16), "white")
    return pil_image_to_png_bytes(image)


def _gif_bytes() -> bytes:
    image = Image.new("RGB", (16, 16), "white")
    buffer = BytesIO()
    image.save(buffer, format="GIF")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _override_image_ad_login(user_id: int = 123):
    from app.api.v1.endpoints import dev_apis as image_ad_endpoint

    app.dependency_overrides[image_ad_endpoint.get_current_user] = lambda: {
        "id": user_id,
        "provider": "test",
        "email": "test@example.com",
        "nickname": "테스트유저",
    }


def test_generate_endpoint_rejects_too_large_image(monkeypatch):
    from app.utils import upload_image_validator

    monkeypatch.setattr(upload_image_validator, "MAX_UPLOAD_IMAGE_BYTES", 10)

    response = client.post(
        "/api/v1/ad/generate",
        data={
            "store_name": "만월",
            "menu_name": "케이크",
            "purpose": "신메뉴 홍보",
            "request_note": "",
            "moods": "cozy",
            "tone": "친근한",
        },
        files={
            "image": ("large.png", _png_bytes(), "image/png"),
        },
    )

    body = response.json()

    assert response.status_code == 413
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "IMAGE_FILE_TOO_LARGE"


def test_generate_endpoint_rejects_corrupted_image():
    response = client.post(
        "/api/v1/ad/generate",
        data={
            "store_name": "만월",
            "menu_name": "케이크",
            "purpose": "신메뉴 홍보",
            "request_note": "",
            "moods": "cozy",
            "tone": "친근한",
        },
        files={
            "image": ("broken.png", b"this-is-not-a-valid-image", "image/png"),
        },
    )

    body = response.json()

    assert response.status_code == 400
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "INVALID_IMAGE_FILE"


def test_generate_endpoint_rejects_gif_image():
    response = client.post(
        "/api/v1/ad/generate",
        data={
            "store_name": "만월",
            "menu_name": "케이크",
            "purpose": "신메뉴 홍보",
            "request_note": "",
            "moods": "cozy",
            "tone": "친근한",
        },
        files={
            "image": ("sample.gif", _gif_bytes(), "image/gif"),
        },
    )

    body = response.json()

    assert response.status_code == 415
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "UNSUPPORTED_IMAGE_FORMAT"


def test_image_ad_endpoint_rejects_gif_base64():
    _override_image_ad_login()

    gif_base64 = encode_image_bytes_to_base64(_gif_bytes())

    response = client.post(
        "/api/v1/dev/ad/image",
        json={
            "input_image_base64": gif_base64,
            "store_name": "만월",
            "menu_name": "케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

    body = response.json()

    assert response.status_code == 415
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "UNSUPPORTED_IMAGE_FORMAT"


def test_image_ad_endpoint_rejects_corrupted_base64():
    _override_image_ad_login()

    corrupted_base64 = base64.b64encode(b"not-a-real-image").decode("utf-8")

    response = client.post(
        "/api/v1/dev/ad/image",
        json={
            "input_image_base64": corrupted_base64,
            "store_name": "만월",
            "menu_name": "케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

    body = response.json()

    assert response.status_code == 400
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "INVALID_IMAGE_FILE"
