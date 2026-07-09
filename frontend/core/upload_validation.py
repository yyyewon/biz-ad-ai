from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from core.config import ALLOWED_IMAGE_TYPES, MAX_UPLOAD_MB

_ALLOWED_FORMATS = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
}


def validate_upload_image_file(
    filename: str | None,
    image_bytes: bytes | None,
) -> tuple[bool, str | None]:
    if not image_bytes:
        return False, "업로드된 이미지 파일이 비어 있어요."

    ext = Path(filename or "").suffix.lower().lstrip(".")

    if ext and ext not in ALLOWED_IMAGE_TYPES:
        return False, "지원하지 않는 파일 형식이에요. JPG, PNG, WEBP 이미지만 올려주세요."

    size_mb = len(image_bytes) / (1024 * 1024)

    if size_mb > MAX_UPLOAD_MB:
        return False, f"파일이 너무 커요 ({size_mb:.1f}MB). {MAX_UPLOAD_MB}MB 이하로 올려주세요."

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            detected_format = (image.format or "").upper()
            image.verify()

    except (UnidentifiedImageError, OSError, ValueError):
        return False, "이미지 파일을 읽을 수 없어요. 손상되지 않은 JPG, PNG, WEBP 파일을 올려주세요."

    normalized_format = _ALLOWED_FORMATS.get(detected_format)

    if normalized_format not in ALLOWED_IMAGE_TYPES:
        return False, "지원하지 않는 이미지 형식이에요. JPG, PNG, WEBP 이미지만 올려주세요."

    return True, None
