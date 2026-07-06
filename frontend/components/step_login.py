"""
로그인 진입 화면
"""
from __future__ import annotations
import base64
from pathlib import Path

import streamlit as st
from core.config import KAKAO_LOGIN_ENDPOINT

_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
_HERO_IMAGE_CANDIDATES = ["login_hero.jpg", "login_hero.jpeg", "login_hero.png", "login_hero.webp"]


@st.cache_resource(show_spinner=False)
def _load_hero_image_style(_mtime: float, path_str: str) -> str:
    path = Path(path_str)
    b64 = base64.b64encode(path.read_bytes()).decode()
    ext = path.suffix.lstrip(".").lower()
    mime = "jpeg" if ext == "jpg" else ext
    return f"background-image:url('data:image/{mime};base64,{b64}');"


def _hero_image_style() -> str:
    for name in _HERO_IMAGE_CANDIDATES:
        path = _ASSET_DIR / name
        if path.exists():
            return _load_hero_image_style(path.stat().st_mtime, str(path))
    return ""


def render() -> None:
    image_style = _hero_image_style()

    html = f"""
    <div class="rg-login-wrap">
      <div class="rg-login-hero">
        <span class="rg-login-hero-badge">📸 AI 광고 콘텐츠 생성</span>
        <div class="rg-login-hero-title">사진 한 장으로<br/>완성되는<br/>우리 가게 인스타그램</div>
        <div class="rg-login-hero-desc">
          배경 교체부터 감성 문구까지,<br/>
          소상공인 두레가 자동으로 만들어드려요.
        </div>
        <div class="rg-login-points">
          <div class="rg-login-point">✓&nbsp;&nbsp;&nbsp;음식 사진 배경을 인스타 감성으로 자동 교체</div>
          <div class="rg-login-point">✓&nbsp;&nbsp;&nbsp;가게 톤에 맞는 광고 문구 자동 생성</div>
          <div class="rg-login-point">✓&nbsp;&nbsp;&nbsp;하루 3회, 누구나 무료로 이용 가능</div>
        </div>
      </div>
      <div class="rg-login-panel">
        <div class="rg-login-panel-image" style="{image_style}">
          <div class="rg-login-panel-fade"></div>
        </div>
        <div class="rg-login-panel-card">
          <div class="rg-login-logo">소상공인 두레</div>
          <div class="rg-login-card-desc">간편하게 카카오 계정으로 시작해 보세요</div>
          <a class="rg-login-kakao-btn" href="{KAKAO_LOGIN_ENDPOINT}" target="_self">카카오로 시작하기</a>
          <div class="rg-login-caption">로그인 시 서비스 이용약관에 동의하는 것으로 간주돼요.</div>
        </div>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)