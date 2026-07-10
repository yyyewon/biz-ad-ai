from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

from app.core import error_constants as errors
from app.core.exceptions import AppException

MAX_UPLOAD_IMAGE_BYTES = 15 * 1024 * 1024
MAX_UPLOAD_IMAGE_PIXELS = 25_000_000
SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


def validate_uploaded_image_bytes(
    image_bytes: bytes | None,
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    """
    업로드 이미지 공통 검증.

    검증 항목:
    - 빈 파일
    - 파일 용량 초과
    - 손상된 이미지
    - 지원하지 않는 이미지 포맷(GIF 등)
    - 비정상적으로 큰 해상도
    """
    if not image_bytes:
        raise AppException(
            errors.EMPTY_IMAGE_FILE,
            detail={
                "filename": filename,
                "content_type": content_type,
            },
        )

    size_bytes = len(image_bytes)

    if size_bytes > MAX_UPLOAD_IMAGE_BYTES:
        raise AppException(
            errors.IMAGE_FILE_TOO_LARGE,
            detail={
                "filename": filename,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "max_bytes": MAX_UPLOAD_IMAGE_BYTES,
                "size_mb": round(size_bytes / (1024 * 1024), 2),
                "max_mb": round(MAX_UPLOAD_IMAGE_BYTES / (1024 * 1024), 2),
            },
        )

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = (image.format or "").upper()
            width, height = image.size
            pixel_count = width * height
            image.verify()

    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AppException(
            errors.INVALID_IMAGE_FILE,
            detail={
                "filename": filename,
                "content_type": content_type,
                "reason": "image_decode_failed",
                "error_type": exc.__class__.__name__,
            },
        ) from exc

    if image_format not in SUPPORTED_IMAGE_FORMATS:
        raise AppException(
            errors.UNSUPPORTED_IMAGE_FORMAT,
            detail={
                "filename": filename,
                "content_type": content_type,
                "detected_format": image_format,
                "supported_formats": sorted(SUPPORTED_IMAGE_FORMATS),
            },
        )

    if pixel_count > MAX_UPLOAD_IMAGE_PIXELS:
        raise AppException(
            errors.IMAGE_FILE_TOO_LARGE,
            detail={
                "filename": filename,
                "content_type": content_type,
                "width": width,
                "height": height,
                "pixel_count": pixel_count,
                "max_pixels": MAX_UPLOAD_IMAGE_PIXELS,
                "reason": "image_resolution_too_large",
            },
        )

    return {
        "filename": filename,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "format": image_format,
        "width": width,
        "height": height,
    }
