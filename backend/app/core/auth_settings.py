"""
소셜 로그인(카카오) / JWT 관련 환경설정
"""
from __future__ import annotations
from dataclasses import dataclass

from app.core.config import get_settings


@dataclass(frozen=True)
class AuthSettings:
    jwt_secret_key: str
    jwt_expires_seconds: int
    kakao_client_id: str
    kakao_client_secret: str
    kakao_redirect_uri: str
    frontend_base_url: str
    dev_tools_enabled: bool


settings = get_settings()
auth_settings = AuthSettings(
    jwt_secret_key=settings.jwt_secret_key,
    jwt_expires_seconds=settings.jwt_expires_seconds,
    kakao_client_id=settings.kakao_client_id,
    kakao_client_secret=settings.kakao_client_secret,
    kakao_redirect_uri=settings.kakao_redirect_uri,
    frontend_base_url=settings.frontend_base_url,
    dev_tools_enabled=settings.dev_tools_enabled,
)
