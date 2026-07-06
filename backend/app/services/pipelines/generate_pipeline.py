import base64
from app.services.pipelines.text_pipeline import run_text_pipeline
from app.api.v1.endpoints.image_preprocess import run_remove_background_and_resize

def run_generate_pipeline(
    store_name: str, 
    menu_name: str, 
    purpose: str, 
    request_note: str, 
    moods: list, 
    tone: str,
    image_bytes: bytes = None
):
    
    """
    텍스트 파이프라인과 이미지 전처리를 총괄하는 마스터 파이프라인
    """
    # 텍스트 카피라이팅 문구 생성
    caption = run_text_pipeline(
        store_name=store_name,
        menu_name=menu_name,
        purpose=purpose,
        request_note=request_note,
        moods=moods,
        tone=tone
    )
    
    images = []
    
    # 이미지 배경 제거 로직
    if image_bytes:
        try:
            # 팀원의 누끼 + 리사이징 함수 호출
            processed_bytes = run_remove_background_and_resize(image_bytes)
            
            if processed_bytes:
                # 프론트엔드 api_client.py 가 base64.b64decode를 하므ww로, 인코딩해서 넘겨줌
                image_base64 = base64.b64encode(processed_bytes).decode("utf-8")
                images.append(image_base64)
        except Exception as e:
            # 이미지 처리가 실패해도 문구 생성을 위해 에러를 터트리지 않고 로그를 남기거나 빈 배열 유지
            pass

    return {
        "caption": caption,
        "images": images  # 전처리된 이미지가 담겨서 나감
    }