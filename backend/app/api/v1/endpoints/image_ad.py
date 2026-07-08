from __future__ import annotations

from fastapi import APIRouter, status
from loguru import logger

from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.schemas.common import APIResponse, success_response
from app.schemas.image_ad import ImageAdRequest
from app.services.pipelines.image_pipeline import generate_image_ads
from app.utils.image_bytes import decode_base64_to_image_bytes


router = APIRouter(prefix="/ad", tags=["ad-image"])


@router.post(
    "/image",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
)
async def create_image_ad(payload: ImageAdRequest):
    """
    이미지 광고 생성 API.

    메모리 기반 처리 기준:
    - input_image_path를 사용하지 않는다.
    - input_image_base64를 bytes로 변환한 뒤 image_pipeline에 전달한다.
    - 생성 이미지는 서버에 저장하지 않는다.
    - 응답에는 base64 이미지 문자열만 포함한다.

    공통 응답 형식:
    {
      "success": true,
      "data": {
        ...ImageAdResponse fields
      },
      "error": null
    }
    """

    try:
        if not payload.input_image_base64:
            raise AppException(
                errors.EMPTY_IMAGE_FILE,
                detail={
                    "endpoint": "/api/v1/ad/image",
                    "field": "input_image_base64",
                },
            )

        source_image_bytes = decode_base64_to_image_bytes(payload.input_image_base64)

        if not source_image_bytes:
            raise AppException(
                errors.EMPTY_IMAGE_FILE,
                detail={
                    "endpoint": "/api/v1/ad/image",
                    "field": "input_image_base64",
                    "reason": "decoded_empty_bytes",
                },
            )

        result = await generate_image_ads(
            payload=payload,
            source_image_bytes=source_image_bytes,
        )

        return success_response(data=result.model_dump())

    except AppException:
        raise

    except Exception as exc:
        logger.exception("image_ad_endpoint_failed | error={}", str(exc))
        raise AppException(
            errors.IMAGE_AD_ENDPOINT_FAILED,
            detail={
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        ) from exc
