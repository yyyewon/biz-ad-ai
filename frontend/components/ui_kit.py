"""
UI Kit
"""
from __future__ import annotations
import base64
import streamlit as st


def alert(message: str, kind: str = "error") -> None:
    st.markdown(f'<div class="rg-alert {kind}">{message}</div>', unsafe_allow_html=True)


def badge_row(items: list[str]) -> None:
    if not items:
        return
    chips = "".join(f'<span class="rg-badge">{item}</span>' for item in items)
    st.markdown(f'<div class="rg-badge-row">{chips}</div>', unsafe_allow_html=True)


def _img_tag(image_bytes: bytes | None, size_label: str) -> str:
    if not image_bytes:
        return f'<span>{size_label}</span>'
    b64 = base64.b64encode(image_bytes).decode()
    return f'<img src="data:image/png;base64,{b64}" />'


def phone_preview(
    store_name: str,
    caption: str,
    hero_image_bytes: bytes | None,
    placeholder_label: str = "이미지 미리보기",
) -> None:
    """
    인스타그램 게시물 형태의 폰 목업 미리보기
    """
    store_label = store_name.strip() if store_name.strip() else "가게 이름"
    caption_html = caption.replace("\n", "<br/>") if caption else "생성된 광고 문구가 여기에 표시돼요."

    html = (
        '<div class="rg-phone">'
        '<div class="rg-phone-screen">'
        '<div class="rg-phone-statusbar"></div>'
        '<div class="rg-phone-header">'
        '<div class="rg-phone-avatar"></div>'
        f'<div class="rg-phone-store">{store_label}</div>'
        '</div>'
        f'<div class="rg-phone-image">{_img_tag(hero_image_bytes, placeholder_label)}</div>'
        '<div class="rg-phone-actions">♥ · 💬 · ✈</div>'
        f'<div class="rg-phone-caption"><b>{store_label}</b>{caption_html}</div>'
        '</div>'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def feed_grid(images: list[bytes], slots: int = 3) -> None:
    """
    인스타 피드 그리드 미리보기
    """
    cells = []
    for i in range(slots):
        if i < len(images):
            b64 = base64.b64encode(images[i]).decode()
            cells.append(f'<div class="rg-grid-cell filled"><img src="data:image/png;base64,{b64}" /></div>')
        else:
            cells.append('<div class="rg-grid-cell">·</div>')
    st.markdown(f'<div class="rg-grid">{"".join(cells)}</div>', unsafe_allow_html=True)