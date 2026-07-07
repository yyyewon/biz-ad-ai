from openai import OpenAI

from app.core.config import get_settings

def run_text_pipeline(store_name: str, menu_name: str, purpose: str, request_note: str, moods: list, tone: str) -> str:
    """
    OpenAI API를 사용하여 광고 문구를 생성하는 텍스트 파이프라인
    """
    settings = get_settings()
    api_key = settings.openai_api_key
    if not api_key:
        return f"[{store_name}] {menu_name} 대박 할인! (API 키가 설정되지 않아 임시 문구가 출력되었습니다.)"

    client = OpenAI(api_key=api_key)
    
    mood_str = ", ".join(moods) if moods else "일반적인"
    prompt = f"""
    당신은 전문 카피라이터입니다. 아래 정보를 바탕으로 SNS(인스타그램)용 광고 문구를 작성해 주세요.
    
    - 가게 이름: {store_name}
    - 메뉴/상품: {menu_name}
    - 광고 목적: {purpose}
    - 분위기: {mood_str}
    - 말투/톤: {tone}
    - 추가 요청사항: {request_note}
    
    문구 중간중간 적절한 이모지를 섞어주고, 맨 마지막 줄에는 관련 해시태그를 5개 이상 달아주세요.
    """

    try:
        response = client.chat.completions.create(
            model=settings.openai_text_model,
            messages=[
                {"role": "system", "content": "너는 소상공인을 위한 친절하고 유능한 광고 카피라이터야."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"문구 생성 중 오류가 발생했습니다: {str(e)}"