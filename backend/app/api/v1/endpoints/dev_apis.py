from __future__ import annotations

import base64
from time import perf_counter

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from loguru import logger

from app.core import error_constants as errors
from app.core.concurrency import generation_limiter
from app.core.deps import get_current_user
from app.core.exceptions import AppException
from app.core.quota import check_and_increment_daily_usage_async
from app.schemas.common import APIResponse, success_response
from app.schemas.image_ad import ImageAdRequest
from app.services.pipelines.image_pipeline import generate_image_ads
from app.services.pipelines.text_pipeline import run_text_pipeline
from app.utils.image_bytes import decode_base64_to_image_bytes
from app.utils.upload_image_validator import validate_uploaded_image_bytes
from app.utils.image_processor import prepare_upload_image

router = APIRouter()

@router.post(
    "/image/preprocess",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
    tags=["Dev - Image Preprocess"],
)
async def preprocess_image(file: UploadFile = File(...)):
    """
    개발/테스트용 이미지 전처리 API

    최종 경로:
    POST /api/v1/dev/image/preprocess

    기능:
    - 업로드 이미지 유효성 검증
    - 비율 유지 리사이즈
    - base64 응답 반환
    """
    # 1) content_type 기본 체크
    if not file.content_type or not file.content_type.startswith("image/"):
        raise AppException(
            errors.INVALID_IMAGE_FILE,
            detail={"content_type": file.content_type},
        )

    # 2) 파일 bytes 읽기
    image_bytes = await file.read()

    if not image_bytes:
        raise AppException(errors.EMPTY_IMAGE_FILE)

    # 3) 업로드 이미지 유효성 검증
    validate_uploaded_image_bytes(
        image_bytes,
        filename=file.filename or "uploaded_image",
        content_type=file.content_type,
    )

    start_time = perf_counter()

    logger.info(
        "image_preprocess_started | filename={} | content_type={} | file_size={}",
        file.filename,
        file.content_type,
        len(image_bytes),
    )

    try:
        # 4) 배경 제거 및 리사이즈 수행
        processed_bytes = prepare_upload_image(image_bytes)

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


@router.post(
    "/ad/text",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
    tags=["Dev - Text Ad"],
)
async def generate_text_only_endpoint(
    store_name: str = Form(..., description="가게 이름"),
    menu_name: str = Form(..., description="메뉴/상품 이름"),
    purpose: str | None = Form(None, description="광고 목적"),
    food: str = Form("", description="음식 종류"),
    tone: str = Form("", description="말투/톤"),
    llm_request: str = Form("", description="광고 문구 생성 요구사항"),
):
    """
    텍스트 광고 문구만 생성하는 API.

    공통 응답 형식:
    {
      "success": true,
      "data": {
        "caption": "..."
      },
      "error": null
    }
    """

    try:

        logger.info(
            "text_ad_endpoint_started | store_name={} | menu_name={} | food={}",
            store_name,
            menu_name,
            food,
        )

        # 광고 문구 생성
        caption = await run_text_pipeline(
            store_name=store_name,
            menu_name=menu_name,
            purpose=purpose or "홍보",
            llm_request=llm_request,
            food=food,
            tone=tone,
        )

        logger.info(
            "text_ad_endpoint_completed | store_name={} | menu_name={} | caption_chars={}",
            store_name,
            menu_name,
            len(caption),
        )

        return success_response(
            data={
                "caption": caption,
            }
        )

    except AppException:
        raise

    except Exception as exc:
        logger.exception(
            "text_ad_endpoint_failed | store_name={} | menu_name={} | error={}",
            store_name,
            menu_name,
            str(exc),
        )
        raise AppException(
            errors.TEXT_AD_ENDPOINT_FAILED,
            detail={
                "store_name": store_name,
                "menu_name": menu_name,
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        ) from exc


@router.post(
    "/ad/image",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
    tags=["Dev - Image Ad"],
)
async def create_image_ad(
    payload: ImageAdRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    개발/테스트용 이미지 광고 단독 생성 API

    최종 경로:
    POST /api/v1/dev/ad/image

    정책:
    - 로그인한 사용자만 호출 가능
    - quota 차감 적용
    - 동시성 제한 적용
    - 입력 이미지는 base64로 전달
    - 공통 응답 포맷 사용
    """
    try:
        # 1) base64 이미지 입력 존재 여부 확인
        if not payload.input_image_base64:
            raise AppException(
                errors.EMPTY_IMAGE_FILE,
                detail={
                    "endpoint": "/api/v1/dev/ad/image",
                    "field": "input_image_base64",
                },
            )

        # 2) base64 → bytes 디코딩
        try:
            source_image_bytes = decode_base64_to_image_bytes(payload.input_image_base64)
        except Exception as exc:
            raise AppException(
                errors.INVALID_IMAGE_FILE,
                detail={
                    "endpoint": "/api/v1/dev/ad/image",
                    "field": "input_image_base64",
                    "reason": "base64_decode_failed",
                    "error_type": exc.__class__.__name__,
                },
            ) from exc

        if not source_image_bytes:
            raise AppException(
                errors.EMPTY_IMAGE_FILE,
                detail={
                    "endpoint": "/api/v1/dev/ad/image",
                    "field": "input_image_base64",
                    "reason": "decoded_empty_bytes",
                },
            )

        # 3) 디코딩된 이미지 bytes 유효성 검증
        validate_uploaded_image_bytes(
            source_image_bytes,
            filename="input_image_base64",
            content_type=None,
        )

        user_id = current_user["id"]

        logger.info(
            "image_ad_endpoint_started | user_id={} | store_name={} | menu_name={} | food_type={} | num_images={}",
            user_id,
            payload.store_name,
            payload.menu_name,
            payload.food_type,
            payload.num_images,
        )

        # 4) 동시성 제한 + quota 차감 + 이미지 생성
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