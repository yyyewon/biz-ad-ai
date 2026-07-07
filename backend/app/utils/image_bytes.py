"""
이미지 bytes 처리 공통 유틸.

서버에 이미지 파일을 저장하지 않고 메모리에서 처리하기 위한 함수들을 모은다.

사용 기준:
- API 응답: bytes → base64 string
- OpenAI/HF SDK 입력: bytes → file-like object
- PIL 처리: Image → PNG bytes
"""

from __future__ import annotations

import base64
from io import BytesIO
from typing import BinaryIO

from PIL import Image


def encode_image_bytes_to_base64(image_bytes: bytes) -> str:
    """
    이미지 bytes를 base64 문자열로 변환한다.
    """

    return base64.b64encode(image_bytes).decode("utf-8")


def decode_base64_to_image_bytes(image_base64: str) -> bytes:
    """
    base64 문자열을 이미지 bytes로 변환한다.

    data:image/png;base64,... 형태도 처리한다.
    """

    if "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]

    return base64.b64decode(image_base64)


def pil_image_to_png_bytes(image: Image.Image) -> bytes:
    """
    PIL Image 객체를 PNG bytes로 변환한다.
    """

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def image_bytes_to_pil(image_bytes: bytes) -> Image.Image:
    """
    이미지 bytes를 PIL Image 객체로 변환한다.
    """

    return Image.open(BytesIO(image_bytes))


def bytes_to_named_file(
    image_bytes: bytes,
    filename: str = "image.png",
) -> BinaryIO:
    """
    이미지 bytes를 OpenAI/HF SDK에 넘길 수 있는 file-like object로 변환한다.

    OpenAI images.edit API는 파일 객체의 name 속성을 참조할 수 있으므로
    BytesIO 객체에 name을 지정한다.
    """

    file_obj = BytesIO(image_bytes)
    file_obj.name = filename
    return file_obj
