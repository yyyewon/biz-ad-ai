"""
이미지 전처리 유틸.

역할:
- 업로드된 이미지 bytes를 PIL Image로 변환
- 비율을 유지한 채 필요 시 다운스케일
- PNG bytes로 반환
"""

from __future__ import annotations

import io

from loguru import logger
from PIL import Image


def _resize_preserving_aspect(
    image: Image.Image,
    *,
    max_width: int,
    max_height: int,
) -> Image.Image:
    width, height = image.size
    if width <= max_width and height <= max_height:
        return image

    scale = min(max_width / width, max_height / height)
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def zoom_center_crop(
    image: Image.Image,
    *,
    zoom_factor: float = 1.45,
) -> Image.Image:
    """
    중앙 기준으로 크롭 후 원본 해상도로 리사이즈해 음식 클로즈업 구도를 유도한다.
  """

    if zoom_factor <= 1.0:
        return image

    width, height = image.size
    crop_width = max(1, int(width / zoom_factor))
    crop_height = max(1, int(height / zoom_factor))
    left = (width - crop_width) // 2
    top = (height - crop_height) // 2
    cropped = image.crop((left, top, left + crop_width, top + crop_height))
    return cropped.resize((width, height), Image.Resampling.LANCZOS)


def shrink_and_pad_for_wider_framing(
    image: Image.Image,
    *,
    subject_scale: float = 0.68,
    padding_rgb: tuple[int, int, int] = (78, 58, 42),
) -> Image.Image:
    """
    images.edit API는 입력 프레이밍을 유지하는 경향이 있어,
    음식을 작게 배치한 뒤 가장자리 여백을 두어 와이드 구도를 유도한다.

    패딩 색은 검정이 아닌 월넛 나무 톤으로, 모델이 여백을 테이블로 채우도록 한다.
    """

    width, height = image.size
    canvas = Image.new("RGB", (width, height), padding_rgb)

    new_width = max(1, int(width * subject_scale))
    new_height = max(1, int(height * subject_scale))
    resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

    offset_x = (width - new_width) // 2
    offset_y = (height - new_height) // 2
    canvas.paste(resized, (offset_x, offset_y))
    return canvas


def prepare_upload_image(
    image_bytes: bytes,
    *,
    max_width: int = 1024,
    max_height: int = 1024,
) -> bytes:
    """
    업로드 이미지를 모델 입력용 PNG bytes로 정규화한다.

    배경 제거(누끼)는 수행하지 않고, 원본 구도와 반찬/테이블 구성을 그대로 유지한다.
    """

    try:
        logger.info(
            "image_preprocess_started | input_bytes={} | max_size={}x{}",
            len(image_bytes) if image_bytes else 0,
            max_width,
            max_height,
        )

        input_image = Image.open(io.BytesIO(image_bytes))

        logger.info(
            "image_preprocess_opened | format={} | mode={} | size={}",
            input_image.format,
            input_image.mode,
            input_image.size,
        )

        output_image = input_image.convert("RGB")
        output_image = _resize_preserving_aspect(
            output_image,
            max_width=max_width,
            max_height=max_height,
        )

        buffer = io.BytesIO()
        output_image.save(buffer, format="PNG")
        result = buffer.getvalue()

        logger.info(
            "image_preprocess_completed | output_bytes={} | output_size={}",
            len(result),
            output_image.size,
        )

        return result

    except Exception as exc:
        logger.exception(
            "image_preprocess_failed | input_bytes={} | max_size={}x{} | error_type={} | error={}",
            len(image_bytes) if image_bytes else 0,
            max_width,
            max_height,
            exc.__class__.__name__,
            str(exc),
        )
        raise
