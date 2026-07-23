"""
UI Kit
"""
from __future__ import annotations
import base64
import io
import logging

from PIL import Image, UnidentifiedImageError
import streamlit as st


logger = logging.getLogger(__name__)


def alert(message: str, kind: str = "error") -> None:
    st.markdown(f'<div class="rg-alert {kind}">{message}</div>', unsafe_allow_html=True)


def quota_exceeded_banner(limit: int | None = None) -> None:
    """
    하루 생성 가능 횟수를 모두 사용했을 때 공통으로 보여주는 안내 배너
    """
    limit_text = f"{limit}회" if limit else "설정된 횟수"
    alert(
        f"⚠️ 하루 생성 가능 {limit_text}를 모두 사용했어요. 내일 다시 시도해 주세요.",
        kind="error",
    )


def badge_row(items: list[str]) -> None:
    if not items:
        return
    chips = "".join(f'<span class="rg-badge">{item}</span>' for item in items)
    st.markdown(f'<div class="rg-badge-row">{chips}</div>', unsafe_allow_html=True)


@st.cache_data(show_spinner=False, max_entries=12, ttl=3600)
def _preview_data_uri(
    image_bytes: bytes,
    *,
    max_size: tuple[int, int],
    quality: int,
) -> str | None:
    """
    WebSocket에 원본 PNG를 싣지 않도록 화면용 JPEG 썸네일 생성
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            preview = source.convert("RGB")
            preview.thumbnail(max_size, Image.Resampling.LANCZOS)
            output = io.BytesIO()
            preview.save(output, format="JPEG", quality=quality, optimize=True)
    except (OSError, UnidentifiedImageError):
        logger.warning("ui_preview_encode_failed | source_bytes=%s", len(image_bytes))
        return None

    preview_bytes = output.getvalue()
    logger.info(
        "ui_preview_encoded | source_bytes=%s | preview_bytes=%s | size=%sx%s",
        len(image_bytes),
        len(preview_bytes),
        preview.width,
        preview.height,
    )
    return f"data:image/jpeg;base64,{base64.b64encode(preview_bytes).decode()}"


def _img_tag(image_bytes: bytes | None, size_label: str) -> str:
    if not image_bytes:
        return f'<span>{size_label}</span>'
    data_uri = _preview_data_uri(image_bytes, max_size=(640, 800), quality=78)
    if data_uri is None:
        return f'<span>{size_label}</span>'
    return f'<img src="{data_uri}" alt="{size_label}" />'


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
            data_uri = _preview_data_uri(images[i], max_size=(320, 400), quality=72)
            if data_uri is not None:
                cells.append(
                    '<div class="rg-grid-cell filled">'
                    f'<img src="{data_uri}" alt="생성 이미지 {i + 1}" />'
                    '</div>'
                )
            else:
                cells.append('<div class="rg-grid-cell">미리보기 불가</div>')
        else:
            cells.append('<div class="rg-grid-cell">·</div>')
    st.markdown(f'<div class="rg-grid">{"".join(cells)}</div>', unsafe_allow_html=True)
