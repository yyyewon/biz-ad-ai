"""
로그인이 필요한 API에서 사용할 FastAPI Dependency
"""
from __future__ import annotations

from fastapi import Header

from app.core.exceptions import AppException
from app.core.security import decode_access_token
from app.core.user_repository import get_user_by_id


async def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppException(
            code="UNAUTHORIZED",
            message="로그인이 필요해요.",
            status_code=401,
        )

    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)

    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AppException(
            code="UNAUTHORIZED",
            message="로그인 정보가 올바르지 않아요. 다시 로그인해 주세요.",
            status_code=401,
        ) from exc

    user = get_user_by_id(user_id)
    if not user:
        raise AppException(
            code="UNAUTHORIZED",
            message="사용자 정보를 찾을 수 없어요. 다시 로그인해 주세요.",
            status_code=401,
        )
    return user
