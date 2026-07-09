from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from loguru import logger

from app.core import error_constants as errors
from app.core.concurrency import generation_limiter
from app.core.deps import get_current_user_optional
from app.core.exceptions import AppException
from app.core.quota import ensure_daily_quota_available_async, increment_daily_usage_async
from app.schemas.common import APIResponse, success_response
from app.services.pipelines.generate_pipeline import run_generate_pipeline
from app.utils.upload_image_validator import validate_uploaded_image_bytes


router = APIRouter()


def _should_count_daily_usage(result: dict) -> bool:
    """이미지 생성이 실제로 성공한 경우에만 일일 사용량을 차감한다."""
    return result.get("image_generation_success") is True


@router.post(
    "/generate",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_ad_endpoint(
    store_name: str = Form(..., description="가게 이름"),
    menu_name: str = Form(..., description="메뉴 이름"),
    purpose: str | None = Form(None, description="광고 목적"),
    request_note: str = Form("", description="요청 사항"),
    moods: str = Form("", description="분위기 (콤마 구분)"),
    tone: str = Form("", description="톤앤매너"),
    image: UploadFile | None = File(None, description="참고용 이미지"),
    current_user: dict | None = Depends(get_current_user_optional),
):
    """
    통합 광고 콘텐츠 생성 API.

    공통 응답 형식:
    {
      "success": true,
      "data": {
        "caption": "...",
        "images": [...],
        "partial_success": false,
        "warnings": [],
        "image_generation_success": true
      },
      "error": null
    }

    주의:
    - pipeline은 내부 결과 dict만 반환한다.
    - API 응답 포맷 래핑은 endpoint에서 success_response로 처리한다.
    """

    try:
        # 콤마로 구분된 분위기 문자열을 리스트로 변환
        mood_list = [m.strip() for m in moods.split(",") if m.strip()] if moods else []

        # 업로드된 이미지 파일 읽기
        image_bytes = None

        if image and image.filename:
            image_bytes = await image.read()
            validate_uploaded_image_bytes(
                image_bytes,
                filename=image.filename,
                content_type=image.content_type,
            )

        # 로그인된 사용자: 한도 확인만 먼저 (실패 시에는 차감하지 않음)
        if current_user:
            await ensure_daily_quota_available_async(current_user["id"])

        logger.info(
            "generate_ad_endpoint_started | store_name={} | menu_name={} | has_image={} | mood_count={}",
            store_name,
            menu_name,
            bool(image_bytes),
            len(mood_list),
        )

        # 동시 생성 요청 수 제한
        async with generation_limiter.slot():
            result = await run_generate_pipeline(
                store_name=store_name,
                menu_name=menu_name,
                purpose=purpose or "홍보",
                request_note=request_note,
                moods=mood_list,
                tone=tone,
                image_bytes=image_bytes,
            )

        if current_user and _should_count_daily_usage(result):
            await increment_daily_usage_async(current_user["id"])

        logger.info(
            "generate_ad_endpoint_completed | store_name={} | menu_name={} | partial_success={}",
            store_name,
            menu_name,
            result.get("partial_success") if isinstance(result, dict) else None,
        )

        return success_response(data=result)

    except AppException:
        raise

    except Exception as exc:
        logger.exception(
            "generate_ad_endpoint_failed | store_name={} | menu_name={} | error={}",
            store_name,
            menu_name,
            str(exc),
        )
        raise AppException(
            errors.GENERATE_AD_ENDPOINT_FAILED,
            detail={
                "store_name": store_name,
                "menu_name": menu_name,
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        ) from exc
