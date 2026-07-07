"""
생성 텍스트 후처리 유틸.

OpenAI, HuggingFace 등 provider 종류와 관계없이
모델이 생성한 문구를 UI에 표시하기 좋은 일반 텍스트로 정리한다.
"""

from __future__ import annotations

import re


def sanitize_generated_caption(text: str) -> str:
    """
    광고 문구에서 UI에 부자연스럽게 보이는 Markdown 문법을 제거한다.

    제거 대상:
    - **굵게**
    - __굵게__
    - `인라인 코드`
    - Markdown 제목: "# 제목"
    - Markdown 목록 기호: "- 문장", "* 문장"

    유지 대상:
    - 마지막 줄의 해시태그
    - 일반 이모지
    - 줄바꿈 구조
    """

    cleaned = (text or "").strip()

    # **강조** 제거
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned, flags=re.DOTALL)

    # __강조__ 제거
    cleaned = re.sub(r"__(.*?)__", r"\1", cleaned, flags=re.DOTALL)

    # `인라인 코드` 제거
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)

    # Markdown heading 제거
    # "# 제목" 형태만 제거하고, 해시태그는 유지한다.
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", cleaned)

    # Markdown list marker 제거
    cleaned = re.sub(r"(?m)^\s*[-*]\s+", "", cleaned)

    # 과도한 빈 줄 정리
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()
