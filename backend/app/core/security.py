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

# Refresh Token 유효기간 기본값 설정 (초 단위: 14일 = 14 * 24 * 60 * 60)
REFRESH_TOKEN_EXPIRES_SECONDS = 14 * 24 * 60 * 60


def create_access_token(user_id: int, provider: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "provider": provider,
        "type": "access",  # 토큰 타입 명시
        "iat": now,
        "exp": now + auth_settings.jwt_expires_seconds,
    }
    return jwt.encode(payload, auth_settings.jwt_secret_key, algorithm=ALGORITHM)


def create_refresh_token(user_id: int, provider: str) -> str:
    """
    유효기간이 긴 Refresh Token을 생성합니다 (기본 14일)
    """
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "provider": provider,
        "type": "refresh",  # 토큰 타입 명시 (Access Token과 구분)
        "iat": now,
        "exp": now + REFRESH_TOKEN_EXPIRES_SECONDS,
    }
    return jwt.encode(payload, auth_settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, auth_settings.jwt_secret_key, algorithms=[ALGORITHM])
        # 혹시 Refresh Token을 Access Token 자리에 넣었는지 검증
        if payload.get("type") == "refresh":
            raise jwt.PyJWTError()
        return payload
    except jwt.PyJWTError as exc:
        raise AppException(
            code="INVALID_TOKEN",
            message="로그인 정보가 유효하지 않아요. 다시 로그인해 주세요.",
            status_code=401,
        ) from exc


def decode_refresh_token(token: str) -> dict[str, Any]:
    """
    Refresh Token의 유효성을 검증합니다.
    """
    try:
        payload = jwt.decode(token, auth_settings.jwt_secret_key, algorithms=[ALGORITHM])
        # 반드시 'refresh' 타입이어야만 유효함
        if payload.get("type") != "refresh":
            raise jwt.PyJWTError()
        return payload
    except jwt.PyJWTError as exc:
        raise AppException(
            code="INVALID_REFRESH_TOKEN",
            message="만료되었거나 유효하지 않은 인증 세션입니다. 다시 로그인해 주세요.",
            status_code=401,
        ) from exc