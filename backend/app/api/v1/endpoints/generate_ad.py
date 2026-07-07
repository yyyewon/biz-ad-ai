from fastapi import APIRouter, Depends, Form, File, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.concurrency import generation_limiter
from app.core.deps import get_current_user_optional
from app.core.quota import check_and_increment_daily_usage_async
from app.services.pipelines.generate_pipeline import run_generate_pipeline

router = APIRouter()


@router.post("")
async def generate_ad_endpoint(
    store_name: str = Form(..., description="가게 이름"),
    menu_name: str = Form(..., description="메뉴 이름"),
    purpose: str = Form(None, description="광고 목적"),
    request_note: str = Form("", description="요청 사항"),
    moods: str = Form("", description="분위기 (콤마 구분)"),
    tone: str = Form("", description="톤앤매너"),
    image: UploadFile = File(None, description="참고용 이미지"),
    current_user: dict | None = Depends(get_current_user_optional),
):
    """
    통합 광고 콘텐츠 생성 API (텍스트 + 이미지 전처리 통합 버전)
    """
    mood_list = [m.strip() for m in moods.split(",") if m.strip()] if moods else []

    # 업로드된 이미지 파일 읽기
    image_bytes = None
    if image and image.filename:
        image_bytes = await image.read()

    # 로그인된 사용자만 하루 생성 횟수 제한을 적용합니다.
    if current_user:
        await check_and_increment_daily_usage_async(current_user["id"])

    # 동시 생성 요청 수 제한
    async with generation_limiter.slot():
        # 마스터 파이프라인 작동
        result = await run_in_threadpool(
            run_generate_pipeline,
            store_name=store_name,
            menu_name=menu_name,
            purpose=purpose or "홍보",
            request_note=request_note,
            moods=mood_list,
            tone=tone,
            image_bytes=image_bytes,
        )

    return result