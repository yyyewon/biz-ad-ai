"""
홍보 목적별 인스타 릴스 하단 후킹 자막 템플릿.

2줄 구조:
- 1줄(lead): 설명 문구 — 일반 굵기
- 2줄(emphasis): 메뉴명·핵심 후킹 — 굵게

frontend/core/config.py PURPOSE_OPTIONS 키와 동기화한다.
"""

from __future__ import annotations

from dataclasses import dataclass

PURPOSE_REELS_HOOK_LINE_TEMPLATES: dict[str, tuple[str, str]] = {
    "신메뉴 홍보": ("{store_name}에 새로 나온", "{menu_name}"),
    "재방문 유도": ("한번 가면 또 생각나는", "{store_name} {menu_name}"),
    "브랜드 인지도 강화": ("{location}에서 유명한", "{store_name} 맛집?"),
    "이벤트/프로모션": ("인당 {price}", "{store_name} {menu_name}?"),
    "매장 분위기 소개": ("{store_name} 안은", "이런 분위기예요"),
    "오픈 소식 알림": ("{location}에 새로 오픈한", "줄 서먹는 {store_name}?"),
}

PURPOSE_REELS_HOOK_WITHOUT_PRICE_LINES: dict[str, tuple[str, str]] = {
    "이벤트/프로모션": ("지금만 이 가격에", "{store_name} {menu_name}?"),
}

DEFAULT_REELS_HOOK_LINES = ("{store_name}에서 만든", "{menu_name}?")


@dataclass(frozen=True)
class ReelsHookCopy:
    lead_line: str
    emphasis_line: str


def _format_hook_lines(
    template: tuple[str, str],
    *,
    store_name: str,
    menu_name: str,
    store_location: str,
    price_text: str,
) -> ReelsHookCopy:
    lead_template, emphasis_template = template
    location_label = (store_location or "").strip() or store_name
    context = {
        "store_name": store_name,
        "menu_name": menu_name,
        "location": location_label,
        "price": price_text,
    }
    return ReelsHookCopy(
        lead_line=lead_template.format(**context).strip(),
        emphasis_line=emphasis_template.format(**context).strip(),
    )


def resolve_reels_hook_lines(
    purpose: str,
    *,
    store_name: str,
    menu_name: str,
    store_location: str = "",
    price_text: str = "",
) -> ReelsHookCopy:
    """홍보 목적과 가게/메뉴 정보로 릴스 2줄 후킹 문구를 만든다."""

    purpose_key = (purpose or "").strip()
    store_label = (store_name or "").strip() or "이 가게"
    menu_label = (menu_name or "").strip() or "이 메뉴"
    location_label = (store_location or "").strip() or store_label
    price_label = (price_text or "").strip()

    if purpose_key == "이벤트/프로모션" and not price_label:
        template = PURPOSE_REELS_HOOK_WITHOUT_PRICE_LINES[purpose_key]
    else:
        template = PURPOSE_REELS_HOOK_LINE_TEMPLATES.get(
            purpose_key,
            DEFAULT_REELS_HOOK_LINES,
        )

    return _format_hook_lines(
        template,
        store_name=store_label,
        menu_name=menu_label,
        store_location=location_label,
        price_text=price_label or "??원",
    )


def resolve_reels_hook_from_purpose(
    purpose: str,
    *,
    store_name: str,
    menu_name: str,
    store_location: str = "",
    price_text: str = "",
) -> str:
    """단일 문자열 후킹 문구 (호환용)."""

    copy = resolve_reels_hook_lines(
        purpose,
        store_name=store_name,
        menu_name=menu_name,
        store_location=store_location,
        price_text=price_text,
    )
    if copy.lead_line and copy.emphasis_line:
        return f"{copy.lead_line} {copy.emphasis_line}"
    return copy.lead_line or copy.emphasis_line
