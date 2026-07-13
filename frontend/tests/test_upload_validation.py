from __future__ import annotations

from io import BytesIO

from PIL import Image

from core.upload_validation import validate_upload_image_file


def _image_bytes(fmt: str = "PNG") -> bytes:
    image = Image.new("RGB", (16, 16), "white")
    buffer = BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def test_validate_upload_image_file_accepts_png():
    ok, message = validate_upload_image_file("sample.png", _image_bytes("PNG"))

    assert ok is True
    assert message is None


def test_validate_upload_image_file_rejects_gif_extension():
    ok, message = validate_upload_image_file("sample.gif", _image_bytes("GIF"))

    assert ok is False
    assert "지원하지 않는" in message


def test_validate_upload_image_file_rejects_corrupted_image():
    ok, message = validate_upload_image_file("broken.png", b"not-a-real-image")

    assert ok is False
    assert "읽을 수 없어요" in message


def test_validate_upload_image_file_rejects_empty_file():
    ok, message = validate_upload_image_file("empty.png", b"")

    assert ok is False
    assert "비어 있어요" in message
