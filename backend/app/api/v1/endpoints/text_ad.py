from fastapi import APIRouter, Form
from app.services.pipelines.text_pipeline import run_text_pipeline
from app.schemas.common import success_response

# text_ad endpoint 전용 라우터입니다.
# router.py에서 prefix="/ad/text" 로 연결할 수 있습니다.
router = APIRouter()

@router.post("")
async def generate_text_only_endpoint(
    store_name: str = Form(..., description="가게 이름"),
    menu_name: str = Form(..., description="메뉴/상품 이름"),
    purpose: str = Form(None, description="광고 목적"),
    request_note: str = Form("", description="추가 요청사항"),
    moods: str = Form("", description="분위기 키워드 (콤마 구분)"),
    tone: str = Form("", description="말투/톤")
):
    """
    텍스트 광고 문구만 단독으로 생성하는 API입니다.

    사용 목적:
    - 이미지 생성 없이 빠르게 카피라이팅 문구만 추출하고 싶을 때 사용
    - 내부 text_pipeline을 직접 호출하여 결과를 반환
    """
    # 콤마(,)로 구분된 분위기 문자열을 리스트로 변환
    mood_list = [m.strip() for m in moods.split(",") if m.strip()] if moods else []

    # 순수 텍스트 파이프라인만 가동
    caption = run_text_pipeline(
        store_name=store_name,
        menu_name=menu_name,
        purpose=purpose,
        request_note=request_note,
        moods=mood_list,
        tone=tone
    )

    # 공통 규격인 success_response로 감싸서 리턴
    return success_response(
        data={
            "caption": caption
        }
    )