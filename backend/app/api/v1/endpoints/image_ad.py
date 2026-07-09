from __future__ import annotations

from fastapi import APIRouter, Depends, status
from loguru import logger

from app.core import error_constants as errors
from app.core.concurrency import generation_limiter
from app.core.deps import get_current_user
from app.core.exceptions import AppException
from app.core.quota import check_and_increment_daily_usage_async
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
async def create_image_ad(
    payload: ImageAdRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    이미지 광고 단독 생성 API.

    정책:
    - 로그인한 사용자만 호출할 수 있다.
    - 생성 요청은 일일 quota를 차감한다.
    - 동시에 처리되는 생성 요청 수를 제한한다.
    - 입력 이미지는 input_image_base64로 받고, 서버에 저장하지 않는다.
    - 응답은 공통 응답 형식(success/data/error)을 사용한다.
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

        try:
            source_image_bytes = decode_base64_to_image_bytes(payload.input_image_base64)
        except Exception as exc:
            raise AppException(
                errors.INVALID_IMAGE_FILE,
                detail={
                    "endpoint": "/api/v1/ad/image",
                    "field": "input_image_base64",
                    "reason": "base64_decode_failed",
                    "error_type": exc.__class__.__name__,
                },
            ) from exc

        if not source_image_bytes:
            raise AppException(
                errors.EMPTY_IMAGE_FILE,
                detail={
                    "endpoint": "/api/v1/ad/image",
                    "field": "input_image_base64",
                    "reason": "decoded_empty_bytes",
                },
            )

        user_id = current_user["id"]

        logger.info(
            "image_ad_endpoint_started | user_id={} | store_name={} | menu_name={} | mood={} | num_images={}",
            user_id,
            payload.store_name,
            payload.menu_name,
            payload.mood,
            payload.num_images,
        )

        async with generation_limiter.slot():
            await check_and_increment_daily_usage_async(user_id)

            result = await generate_image_ads(
                payload=payload,
                source_image_bytes=source_image_bytes,
            )

        logger.info(
            "image_ad_endpoint_completed | user_id={} | request_id={} | image_count={}",
            user_id,
            result.request_id,
            len(result.images),
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
