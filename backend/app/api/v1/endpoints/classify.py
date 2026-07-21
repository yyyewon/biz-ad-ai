from fastapi import APIRouter, UploadFile, File, status
from app.schemas.common import APIResponse, success_response

router = APIRouter()

from fastapi import APIRouter, UploadFile, File, status, Depends
from loguru import logger


from app.core.deps import get_current_user
from app.core.exceptions import AppException
from app.core import errors
from app.schemas.common import APIResponse, success_response
from app.services.providers.food_classifier_provider import food_classifier_provider
from app.utils.upload_image_validator import validate_uploaded_image_bytes

import asyncio

router = APIRouter()


@router.post(
    "/classify-food",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
    tags=["Dev - Food Classification"],
)
async def classify_food_endpoint(
    file: UploadFile = File(..., description="분류할 음식 이미지"),
):
    """
    이미지를 받아 어떤 음식 카테고리에 속하는지 분류하여 반환합니다.

    최종 경로:
    POST /api/v1/dev/classify-food

    정책:
    - 로그인한 사용자만 호출 가능
    - 입력 이미지는 multipart/form-data로 전달
    - 공통 응답 포맷 사용
    """
    try:
        # 파일 존재 여부 확인
        if not file or not file.filename:
            raise AppException(
                errors.EMPTY_IMAGE_FILE,
                detail={
                    "endpoint": "/api/v1/dev/classify-food",
                    "field": "file",
                },
            )

        # 파일 bytes 읽기
        try:
            image_bytes = await file.read()
        except Exception as exc:
            raise AppException(
                errors.INVALID_IMAGE_FILE,
                detail={
                    "endpoint": "/api/v1/dev/classify-food",
                    "field": "file",
                    "reason": "file_read_failed",
                    "error_type": exc.__class__.__name__,
                },
            ) from exc

        if not image_bytes:
            raise AppException(
                errors.EMPTY_IMAGE_FILE,
                detail={
                    "endpoint": "/api/v1/dev/classify-food",
                    "field": "file",
                    "reason": "empty_bytes",
                },
            )

        # 이미지 bytes 유효성 검증 (content-type, 크기, 실제 이미지 여부 등)
        validate_uploaded_image_bytes(
            image_bytes,
            filename=file.filename,
            content_type=file.content_type,
        )

        logger.info(
            "classify_food_endpoint_started | user_id={} | filename={} | content_type={}",
            file.filename,
            file.content_type,
        )

        # 분류 수행 (동기 추론이므로 이벤트 루프 블로킹 방지를 위해 스레드로 위임)
        try:
            predicted_food = await asyncio.to_thread(
                food_classifier_provider.classify, image_bytes
            )
        except Exception as exc:
            raise AppException(
                errors.FOOD_CLASSIFICATION_FAILED,
                detail={
                    "endpoint": "/api/v1/dev/classify-food",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            ) from exc

        logger.info(
            "classify_food_endpoint_completed | user_id={} | predicted_food={}",
            predicted_food,
        )

        return success_response(data={"predicted_food": predicted_food})

    except AppException:
        raise

    except Exception as exc:
        logger.exception("classify_food_endpoint_failed | error={}", str(exc))

        raise AppException(
            errors.FOOD_CLASSIFICATION_ENDPOINT_FAILED,
            detail={
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        ) from exc