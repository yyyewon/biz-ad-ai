import base64

from fastapi.testclient import TestClient

from app.main import app
from app.api.v1.endpoints import image_preprocess


client = TestClient(app)


def test_image_preprocess_success(monkeypatch):
    """
    이미지 전처리 API 성공 테스트입니다.

    실제 rembg 모델을 실행하지 않고,
    run_remove_background_and_resize 함수를 monkeypatch하여
    API 요청/응답 구조만 검증합니다.
    """

    fake_processed_bytes = b"processed-image-bytes"

    def fake_preprocess(image_bytes: bytes) -> bytes:
        assert image_bytes == b"input-image-bytes"
        return fake_processed_bytes

    monkeypatch.setattr(
        image_preprocess,
        "run_remove_background_and_resize",
        fake_preprocess,
    )

    response = client.post(
        "/api/v1/image/preprocess",
        files={
            "file": (
                "sample.png",
                b"input-image-bytes",
                "image/png",
            )
        },
    )

    assert response.status_code == 200

    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["mime_type"] == "image/png"
    assert body["data"]["filename"] == "sample.png"
    assert body["data"]["image_base64"] == base64.b64encode(
        fake_processed_bytes
    ).decode("utf-8")


def test_image_preprocess_invalid_file_type():
    """
    이미지가 아닌 파일 업로드 시 400 에러가 반환되는지 확인합니다.
    """

    response = client.post(
        "/api/v1/image/preprocess",
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
    """
    빈 이미지 파일 업로드 시 400 에러가 반환되는지 확인합니다.
    """

    response = client.post(
        "/api/v1/image/preprocess",
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
