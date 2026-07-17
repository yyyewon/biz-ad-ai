"""
홍보 목적 × 톤앤매너별 포스터 상단 카피(짧은 태그) 매핑.

SNS 캡션과 분리해 이미지 포스터 상단에 넣을 8~15자 내외 문구를 고정한다.
frontend/core/config.py 의 PURPOSE_OPTIONS, TONE_OPTIONS 키와 동기화한다.
"""

from __future__ import annotations

DEFAULT_TONE = "캐주얼·친근"

PURPOSE_TONE_POSTER_TAGLINES: dict[str, dict[str, str]] = {
    "신메뉴 홍보": {
        "캐주얼·친근": "신메뉴 나왔어요",
        "정중·신뢰": "신메뉴를 선보입니다",
        "고급·감성": "새로운 한 접시",
        "유머·이벤트": "드디어 나왔다!",
    },
    "재방문 유도": {
        "캐주얼·친근": "또 생각나는 맛",
        "정중·신뢰": "다시 찾아주세요",
        "고급·감성": "기억에 남는 맛",
        "유머·이벤트": "한번 더 올래?",
    },
    "브랜드 인지도 강화": {
        "캐주얼·친근": "단골이 말해요",
        "정중·신뢰": "믿고 찾는 맛",
        "고급·감성": "오래 기억될 맛",
        "유머·이벤트": "여기 맞지?",
    },
    "이벤트/프로모션": {
        "캐주얼·친근": "지금이 찬스!",
        "정중·신뢰": "프로모션 진행 중",
        "고급·감성": "특별한 혜택",
        "유머·이벤트": "놓치면 손해!",
    },
    "매장 분위기 소개": {
        "캐주얼·친근": "이런 분위기예요",
        "정중·신뢰": "매장의 하루",
        "고급·감성": "공간의 온기",
        "유머·이벤트": "분위기 실화?",
    },
    "오픈 소식 알림": {
        "캐주얼·친근": "곧 오픈해요!",
        "정중·신뢰": "오픈을 앞두고",
        "고급·감성": "새로운 시작",
        "유머·이벤트": "문 연다!",
    },
}


def resolve_poster_headline(purpose: str, tone: str | None = None) -> str:
    """홍보 목적과 톤앤매너로 포스터 상단 카피를 반환한다. 매핑 없으면 빈 문자열."""

    purpose_key = (purpose or "").strip()
    if not purpose_key:
        return ""

    tone_key = (tone or "").strip() or DEFAULT_TONE
    tone_block = PURPOSE_TONE_POSTER_TAGLINES.get(purpose_key, {})

    if tone_key in tone_block:
        return tone_block[tone_key]

    return tone_block.get(DEFAULT_TONE, "")


def resolve_poster_headline_from_purpose(purpose: str) -> str:
    """(호환용) 기본 톤으로 포스터 상단 카피를 반환한다."""

    return resolve_poster_headline(purpose, DEFAULT_TONE)
