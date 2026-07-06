"""
소셜 로그인(카카오) / JWT 관련 환경설정
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthSettings:
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "CHANGE_ME_DEV_ONLY_SECRET")
    jwt_expires_seconds: int = int(os.getenv("JWT_EXPIRES_SECONDS", str(60 * 60 * 24 * 7)))

    kakao_client_id: str = os.getenv("KAKAO_CLIENT_ID", "")
    kakao_client_secret: str = os.getenv("KAKAO_CLIENT_SECRET", "")
    kakao_redirect_uri: str = os.getenv(
        "KAKAO_REDIRECT_URI", "http://localhost:8010/api/v1/auth/kakao/callback"
    )

    frontend_base_url: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:8501")

    dev_tools_enabled: bool = os.getenv("DEV_TOOLS_ENABLED", "false").lower() == "true"


auth_settings = AuthSettings()
