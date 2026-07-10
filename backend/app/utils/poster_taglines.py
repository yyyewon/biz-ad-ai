"""
홍보 목적별 포스터 상단 카피(짧은 태그) 매핑.

SNS 캡션과 분리해 이미지 포스터 상단에 넣을 8~15자 내외 문구를 고정한다.
frontend/core/config.py PURPOSE_OPTIONS 키와 동기화한다.
"""

from __future__ import annotations

PURPOSE_POSTER_TAGLINES: dict[str, str] = {
    "신메뉴 홍보": "신메뉴 출시",
    "재방문 유도": "또 오고 싶은 맛",
    "브랜드 인지도 강화": "믿고 찾는 맛",
    "이벤트/프로모션": "이벤트 진행 중",
    "매장 분위기 소개": "따뜻한 한 끼",
    "오픈 소식 알림": "오픈 준비 완료",
}


def resolve_poster_headline_from_purpose(purpose: str) -> str:
    """홍보 목적 pill 값을 포스터 상단 카피로 변환한다. 매핑 없으면 빈 문자열."""

    return PURPOSE_POSTER_TAGLINES.get((purpose or "").strip(), "")
