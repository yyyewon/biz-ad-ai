from fastapi import APIRouter, Form, File, UploadFile
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
    image: UploadFile = File(None, description="참고용 이미지")
):
    """
    통합 광고 콘텐츠 생성 API (텍스트 + 이미지 전처리 통합 버전)
    """
    mood_list = [m.strip() for m in moods.split(",") if m.strip()] if moods else []

    # 업로드된 이미지 파일 읽기
    image_bytes = None
    if image and image.filename:
        image_bytes = await image.read()

    # 마스터 파이프라인 작동
    result = run_generate_pipeline(
        store_name=store_name,
        menu_name=menu_name,
        purpose=purpose or "홍보",
        request_note=request_note,
        moods=mood_list,
        tone=tone,
        image_bytes=image_bytes
    )

    return result