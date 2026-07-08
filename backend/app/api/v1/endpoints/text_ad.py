from __future__ import annotations

from fastapi import APIRouter, Form
from loguru import logger

from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.schemas.common import APIResponse, success_response
from app.services.pipelines.text_pipeline import run_text_pipeline


router = APIRouter()


@router.post("", response_model=APIResponse)
async def generate_text_only_endpoint(
    store_name: str = Form(..., description="가게 이름"),
    menu_name: str = Form(..., description="메뉴/상품 이름"),
    purpose: str | None = Form(None, description="광고 목적"),
    request_note: str = Form("", description="추가 요청사항"),
    moods: str = Form("", description="분위기 키워드 (콤마 구분)"),
    tone: str = Form("", description="말투/톤"),
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
        # 콤마로 구분된 분위기 문자열을 리스트로 변환
        mood_list = [m.strip() for m in moods.split(",") if m.strip()] if moods else []

        logger.info(
            "text_ad_endpoint_started | store_name={} | menu_name={} | mood_count={}",
            store_name,
            menu_name,
            len(mood_list),
        )

        # 광고 문구 생성
        caption = await run_text_pipeline(
            store_name=store_name,
            menu_name=menu_name,
            purpose=purpose or "홍보",
            request_note=request_note,
            moods=mood_list,
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
