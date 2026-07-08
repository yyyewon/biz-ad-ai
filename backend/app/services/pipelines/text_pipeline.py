"""
광고 문구 생성 pipeline.

역할:
- 사용자 입력을 광고 카피라이팅 프롬프트로 변환한다.
- 실제 모델 호출은 provider factory에서 가져온 text provider가 담당한다.
- OpenAI/HF 전환은 backend/config/model.yaml의 active_profile로 관리한다.
- 모델이 Markdown 문법을 섞어 출력하더라도 공통 sanitizer로 후처리한다.
"""

from __future__ import annotations

from loguru import logger

from app.services.providers.factory import get_text_provider
from app.utils.text_sanitizer import sanitize_generated_caption


def run_text_pipeline(
    store_name: str,
    menu_name: str,
    purpose: str,
    request_note: str,
    moods: list,
    tone: str,
) -> str:
    """
    광고 문구 생성 파이프라인.

    provider 종류와 관계없이 최종 광고 문구에는 공통 sanitizer를 적용한다.
    따라서 추후 HF text provider가 추가되어도 동일한 후처리 규칙이 적용된다.
    """

    mood_str = ", ".join(moods) if moods else "일반적인"

    prompt = f"""
아래 정보를 바탕으로 SNS(인스타그램)용 광고 문구를 작성해 주세요.

- 가게 이름: {store_name}
- 메뉴/상품: {menu_name}
- 광고 목적: {purpose}
- 분위기: {mood_str}
- 말투/톤: {tone}
- 추가 요청사항: {request_note}

작성 조건:
1. 문구 중간중간 적절한 이모지를 섞어 주세요.
2. 마지막 줄에는 관련 해시태그를 5개 이상 작성해 주세요.
3. 과장되거나 허위로 보일 수 있는 표현은 피해주세요.
""".strip()

    system_instruction = (
        "너는 소상공인을 위한 친절하고 유능한 광고 카피라이터야. "
    )

    logger.info(
        "text_pipeline_started | store_name={} | menu_name={} | mood_count={}",
        store_name,
        menu_name,
        len(moods or []),
    )

    provider = get_text_provider()

    raw_result = provider.generate_text(
        prompt=prompt,
        system_instruction=system_instruction,
    )

    result = sanitize_generated_caption(raw_result)

    logger.info(
        "text_pipeline_completed | store_name={} | menu_name={} | raw_chars={} | output_chars={}",
        store_name,
        menu_name,
        len(raw_result),
        len(result),
    )

    return result
