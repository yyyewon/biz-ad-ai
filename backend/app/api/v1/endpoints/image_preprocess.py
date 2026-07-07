from __future__ import annotations

import base64
from time import perf_counter

from fastapi import APIRouter, File, UploadFile
from loguru import logger

from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.schemas.common import APIResponse, success_response


router = APIRouter()


def run_remove_background_and_resize(image_bytes: bytes) -> bytes:
    """
    이미지 배경 제거 및 리사이즈 함수.

    실제 처리는 app.image_processor.remove_background_and_resize가 담당한다.
    """

    try:
        from backend.app.utils.image_processor import remove_background_and_resize

    except SystemExit as exc:
        raise AppException(
            errors.IMAGE_PREPROCESS_DEPENDENCY_ERROR,
            detail={
                "reason": "rembg CPU backend가 필요합니다.",
                "hint": 'requirements에 "rembg[cpu]"가 포함되어야 합니다.',
            },
        ) from exc

    except ImportError as exc:
        raise AppException(
            errors.IMAGE_PREPROCESS_DEPENDENCY_ERROR,
            detail={
                "reason": "image_processor import failed",
                "error": str(exc),
            },
        ) from exc

    return remove_background_and_resize(image_bytes)


@router.post("/preprocess", response_model=APIResponse)
async def preprocess_image(file: UploadFile = File(...)):
    """
    이미지 전처리 API.

    공통 응답 형식:
    {
      "success": true,
      "data": {
        "image_base64": "...",
        "mime_type": "image/png",
        "filename": "..."
      },
      "error": null
    }
    """

    # 이미지 파일 형식 검증
    if not file.content_type or not file.content_type.startswith("image/"):
        raise AppException(
            errors.INVALID_IMAGE_FILE,
            detail={"content_type": file.content_type},
        )

    # 업로드 파일 bytes 읽기
    image_bytes = await file.read()

    if not image_bytes:
        raise AppException(errors.EMPTY_IMAGE_FILE)

    start_time = perf_counter()

    logger.info(
        "image_preprocess_started | filename={} | content_type={} | file_size={}",
        file.filename,
        file.content_type,
        len(image_bytes),
    )

    try:
        # 이미지 배경 제거 및 리사이즈
        processed_bytes = run_remove_background_and_resize(image_bytes)

    except AppException:
        raise

    except Exception as exc:
        logger.exception(
            "image_preprocess_failed | filename={} | error={}",
            file.filename,
            str(exc),
        )
        raise AppException(
            errors.IMAGE_PREPROCESS_FAILED,
            detail={
                "filename": file.filename,
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        ) from exc

    if not processed_bytes:
        raise AppException(
            errors.IMAGE_PREPROCESS_EMPTY_RESULT,
            detail={"filename": file.filename},
        )

    image_base64 = base64.b64encode(processed_bytes).decode("utf-8")
    elapsed_ms = round((perf_counter() - start_time) * 1000, 2)

    logger.info(
        "image_preprocess_completed | filename={} | output_size={} | base64_length={} | elapsed_ms={}",
        file.filename,
        len(processed_bytes),
        len(image_base64),
        elapsed_ms,
    )

    return success_response(
        data={
            "image_base64": image_base64,
            "mime_type": "image/png",
            "filename": file.filename,
            "elapsed_ms": elapsed_ms,
        }
    )
