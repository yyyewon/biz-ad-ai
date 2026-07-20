"""
홍보 목적 × 톤앤매너별 포스터 카피 매핑.

SNS 캡션과 분리해 이미지 포스터에 넣을 짧은 문구를 고정한다.
frontend/core/config.py 의 PURPOSE_OPTIONS, TONE_OPTIONS 키와 동기화한다.

각 항목:
- headline: 상단 메인 카피 (8~14자)
- subline: 메뉴명 위 보조 한 줄 (선택, 10~18자)
- sticker: 작은 라벨 pill (선택). 목적별 예: NEW / OPEN / SALE / BEST / HOT / MOOD / EVENT / SEASON / TRUST / OFFER
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TONE = "캐주얼·친근"


@dataclass(frozen=True)
class PosterTaglineCopy:
    """포스터 상단 카피 세트."""

    headline: str
    subline: str = ""
    sticker: str = ""


def _copy(
    headline: str,
    *,
    subline: str = "",
    sticker: str = "",
) -> PosterTaglineCopy:
    return PosterTaglineCopy(
        headline=headline,
        subline=subline,
        sticker=sticker,
    )


PURPOSE_TONE_POSTER_COPY: dict[str, dict[str, PosterTaglineCopy]] = {
    "신메뉴 홍보": {
        "캐주얼·친근": _copy("새 메뉴 나왔어요", subline="오늘부터 만나보세요", sticker="NEW"),
        "정중·신뢰": _copy("신메뉴를 소개합니다", subline="정성껏 준비했습니다", sticker="NEW"),
        "고급·감성": _copy("새로운 시즌 메뉴", subline="감각을 채우는 새로운 맛", sticker="SEASON"),
        "유머·이벤트": _copy("드디어 나왔다!", subline="안 먹어보면 후회할 맛", sticker="NEW"),
    },
    "재방문 유도": {
        "캐주얼·친근": _copy("또 생각나는 맛", subline="오늘도 드시러 오세요", sticker="BEST"),
        "정중·신뢰": _copy("늘 같은 맛으로", subline="오늘도 정성껏 준비했습니다", sticker="BEST"),
        "고급·감성": _copy("기억에 남는 순간", subline="다시 느껴보세요", sticker="PICK"),
        "유머·이벤트": _copy("또 오실 거죠?", subline="아는 맛이 제일 무서운 법", sticker="HOT"),
    },
    "브랜드 인지도 강화": {
        "캐주얼·친근": _copy("단골이 많은 이유", subline="한 번 맛보면 반하니까", sticker="HOT"),
        "정중·신뢰": _copy("믿고 찾는 맛", subline="꾸준히 사랑받는 공간", sticker="TRUST"),
        "고급·감성": _copy("오래 기억될 맛", subline="우리만의 깊이로", sticker="SIGN"),
        "유머·이벤트": _copy("소문 듣고 오셨나요?", subline="들어올 땐 마음대로, 나갈 땐 단골", sticker="HOT"),
    },
    "이벤트/프로모션": {
        "캐주얼·친근": _copy("지금이 찬스!", subline="특별한 가격으로 만나보세요", sticker="SALE"),
        "정중·신뢰": _copy("특별 혜택 안내", subline="기간 한정으로 준비했습니다", sticker="OFFER"),
        "고급·감성": _copy("특별한 제안", subline="당신만을 위해 준비한 혜택", sticker="EVENT"),
        "유머·이벤트": _copy("안 오면 후회할 걸요?", subline="지금이 바로 그 기회!", sticker="SALE"),
    },
    "매장 분위기 소개": {
        "캐주얼·친근": _copy("이런 분위기예요", subline="편하게 들러 쉬어가세요", sticker="MOOD"),
        "정중·신뢰": _copy("정성을 담는 공간", subline="편안한 시간을 선물합니다", sticker="SPACE"),
        "고급·감성": _copy("공간의 온기", subline="머무는 시간까지 특별하게", sticker="ATMOS"),
        "유머·이벤트": _copy("분위기 실화?", subline="사진보다 실물이 훨씬 예쁜 곳", sticker="VIBE"),
    },
    "오픈 소식 알림": {
        "캐주얼·친근": _copy("곧 만나러 갑니다", subline="설레는 마음으로 기다려 주세요", sticker="OPEN"),
        "정중·신뢰": _copy("오픈을 앞두고", subline="새로운 공간으로 찾아뵙겠습니다", sticker="OPEN"),
        "고급·감성": _copy("새로운 시작", subline="곧 만나뵙겠습니다", sticker="GRAND"),
        "유머·이벤트": _copy("드디어 오픈!", subline="준비는 끝났다, 몸만 오세요", sticker="OPEN"),
    },
}


def resolve_poster_copy(purpose: str, tone: str | None = None) -> PosterTaglineCopy:
    """홍보 목적과 톤앤매너로 포스터 카피 세트를 반환한다."""

    purpose_key = (purpose or "").strip()
    if not purpose_key:
        return PosterTaglineCopy(headline="")

    tone_key = (tone or "").strip() or DEFAULT_TONE
    tone_block = PURPOSE_TONE_POSTER_COPY.get(purpose_key, {})
    if tone_key in tone_block:
        return tone_block[tone_key]
    return tone_block.get(DEFAULT_TONE, PosterTaglineCopy(headline=""))


def resolve_poster_headline(purpose: str, tone: str | None = None) -> str:
    """홍보 목적과 톤앤매너로 포스터 상단 카피를 반환한다. 매핑 없으면 빈 문자열."""

    return resolve_poster_copy(purpose, tone).headline


def resolve_poster_headline_from_purpose(purpose: str) -> str:
    """(호환용) 기본 톤으로 포스터 상단 카피를 반환한다."""

    return resolve_poster_headline(purpose, DEFAULT_TONE)
