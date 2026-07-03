import base64
from time import perf_counter

from fastapi import APIRouter, File, UploadFile
from loguru import logger

from app.core.exceptions import AppException
from app.schemas.common import success_response


router = APIRouter()


def run_remove_background_and_resize(image_bytes: bytes) -> bytes:
    """
    팀원이 구현한 remove_background_and_resize 함수를 호출합니다.

    rembg는 onnxruntime 백엔드가 없을 때 ImportError가 아니라
    SystemExit를 발생시킬 수 있으므로 여기서 명시적으로 처리합니다.
    """

    try:
        from app.image_processor import remove_background_and_resize
    except SystemExit as exc:
        raise AppException(
            code="IMAGE_PREPROCESS_DEPENDENCY_ERROR",
            message="이미지 전처리 의존성이 올바르게 설치되지 않았습니다.",
            status_code=500,
            detail='rembg CPU backend가 필요합니다. requirements에 "rembg[cpu]"가 포함되어야 합니다.',
        ) from exc
    except ImportError as exc:
        raise AppException(
            code="IMAGE_PREPROCESS_DEPENDENCY_ERROR",
            message="이미지 전처리 의존성이 설치되지 않았습니다.",
            status_code=500,
            detail=str(exc),
        ) from exc

    return remove_background_and_resize(image_bytes)


@router.post("/preprocess")
async def preprocess_image(file: UploadFile = File(...)):
    """
    이미지 전처리 API입니다.

    처리 내용:
    - multipart/form-data 이미지 업로드
    - app/image_processor.py의 remove_background_and_resize 실행
    - 전처리 결과 이미지를 base64로 반환
    """

    if not file.content_type or not file.content_type.startswith("image/"):
        raise AppException(
            code="INVALID_IMAGE_FILE",
            message="이미지 파일만 업로드할 수 있습니다.",
            status_code=400,
            detail={"content_type": file.content_type},
        )

    image_bytes = await file.read()

    if not image_bytes:
        raise AppException(
            code="EMPTY_IMAGE_FILE",
            message="업로드된 이미지 파일이 비어 있습니다.",
            status_code=400,
        )

    start_time = perf_counter()

    logger.info(
        "image_preprocess_started | filename={} | content_type={} | file_size={}",
        file.filename,
        file.content_type,
        len(image_bytes),
    )

    try:
        processed_bytes = run_remove_background_and_resize(image_bytes)
    except AppException:
        raise
    except Exception as exc:
        raise AppException(
            code="IMAGE_PREPROCESS_FAILED",
            message="이미지 전처리 중 오류가 발생했습니다.",
            status_code=500,
            detail=str(exc),
        ) from exc

    if not processed_bytes:
        raise AppException(
            code="IMAGE_PREPROCESS_EMPTY_RESULT",
            message="이미지 전처리 결과가 비어 있습니다.",
            status_code=500,
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
        }
    )
