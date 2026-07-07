"""
이미지 전처리 유틸.

역할:
- 업로드된 이미지 bytes를 PIL Image로 변환
- rembg로 배경 제거
- target_size 기준으로 리사이즈
- PNG bytes로 반환
"""

from __future__ import annotations

import io

from loguru import logger
from PIL import Image
from rembg import remove


def remove_background_and_resize(
    image_bytes: bytes,
    target_size: tuple[int, int] = (512, 512),
) -> bytes:
    """
    이미지 배경을 제거하고 지정된 크기로 리사이즈한 뒤 PNG bytes로 반환한다.

    Args:
        image_bytes:
            입력 이미지 bytes.
        target_size:
            리사이즈할 이미지 크기. 기본값은 (512, 512).

    Returns:
        배경 제거 및 리사이즈가 완료된 PNG bytes.

    Raises:
        Exception:
            PIL 이미지 열기, rembg 처리, resize, PNG 변환 중 발생한 예외를 그대로 전달한다.
            상위 endpoint 또는 pipeline에서 AppException으로 변환한다.
    """

    try:
        logger.info(
            "image_preprocess_started | input_bytes={} | target_size={}",
            len(image_bytes) if image_bytes else 0,
            target_size,
        )

        # 1. 입력받은 바이너리 데이터를 이미지 객체로 변환한다.
        input_image = Image.open(io.BytesIO(image_bytes))

        logger.info(
            "image_preprocess_opened | format={} | mode={} | size={}",
            input_image.format,
            input_image.mode,
            input_image.size,
        )

        # 2. rembg 라이브러리로 배경 제거를 수행한다.
        logger.info("image_preprocess_remove_background_started")
        output_image = remove(input_image)

        # 3. 투명도 보존을 위해 RGBA로 정규화한다.
        output_image = output_image.convert("RGBA")

        # 4. AI 모델 입력 규격에 맞게 크기를 변환한다.
        logger.info("image_preprocess_resize_started | target_size={}", target_size)
        output_image = output_image.resize(target_size, Image.Resampling.LANCZOS)

        # 5. 처리된 이미지를 PNG bytes로 변환한다.
        buffer = io.BytesIO()
        output_image.save(buffer, format="PNG")
        result = buffer.getvalue()

        logger.info(
            "image_preprocess_completed | output_bytes={} | output_size={}",
            len(result),
            target_size,
        )

        return result

    except Exception as exc:
        logger.exception(
            "image_preprocess_failed | input_bytes={} | target_size={} | error_type={} | error={}",
            len(image_bytes) if image_bytes else 0,
            target_size,
            exc.__class__.__name__,
            str(exc),
        )
        raise
