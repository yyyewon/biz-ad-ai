from __future__ import annotations

import base64
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.api.v1.endpoints import dev_apis as image_preprocess
from app.main import app

client = TestClient(app)


def _png_bytes() -> bytes:
    image = Image.new("RGB", (16, 16), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_preprocess_success(monkeypatch):
    """
    이미지 전처리 API 성공 테스트.

    실제 rembg 모델을 실행하지 않고,
    remove_background_and_resize 함수를 monkeypatch하여
    API 요청/응답 구조만 검증한다.
    """

    input_bytes = _png_bytes()
    fake_processed_bytes = b"processed-image-bytes"

    def fake_preprocess(image_bytes: bytes) -> bytes:
        assert image_bytes == input_bytes
        return fake_processed_bytes

    monkeypatch.setattr(
        image_preprocess,
        "remove_background_and_resize",
        fake_preprocess,
    )

    response = client.post(
        "/api/v1/dev/image/preprocess",
        files={
            "file": (
                "sample.png",
                input_bytes,
                "image/png",
            )
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["image_base64"] == base64.b64encode(fake_processed_bytes).decode("utf-8")
    assert body["data"]["mime_type"] == "image/png"
    assert body["data"]["filename"] == "sample.png"
    assert "elapsed_ms" in body["data"]


def test_image_preprocess_invalid_file_type():
    response = client.post(
        "/api/v1/dev/image/preprocess",
        files={
            "file": (
                "sample.txt",
                b"not-image",
                "text/plain",
            )
        },
    )

    assert response.status_code == 400

    body = response.json()

    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "INVALID_IMAGE_FILE"


def test_image_preprocess_empty_file():
    response = client.post(
        "/api/v1/dev/image/preprocess",
        files={
            "file": (
                "empty.png",
                b"",
                "image/png",
            )
        },
    )

    assert response.status_code == 400

    body = response.json()

    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "EMPTY_IMAGE_FILE"
