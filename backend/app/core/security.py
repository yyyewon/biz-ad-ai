"""
JWT 발급 / 검증 모듈
"""
from __future__ import annotations

import time
from typing import Any

import jwt

from app.core.auth_settings import auth_settings
from app.core.exceptions import AppException

ALGORITHM = "HS256"


def create_access_token(user_id: int, provider: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "provider": provider,
        "iat": now,
        "exp": now + auth_settings.jwt_expires_seconds,
    }
    return jwt.encode(payload, auth_settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, auth_settings.jwt_secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AppException(
            code="INVALID_TOKEN",
            message="로그인 정보가 유효하지 않아요. 다시 로그인해 주세요.",
            status_code=401,
        ) from exc
