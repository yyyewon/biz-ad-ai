"""
로그인이 필요한 API에서 사용할 FastAPI Dependency
"""
from __future__ import annotations

from fastapi import Header, Request

from app.core.exceptions import AppException
from app.core.security import decode_access_token
from app.core.user_repository import get_user_by_id


def _extract_token(request: Request, authorization: str | None) -> str | None:
    """
    쿠키를 먼저 보고, 없으면 Authorization 헤더에서 Bearer 토큰을 꺼낸다
    """
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return cookie_token.strip()

    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()

    return None


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    token = _extract_token(request, authorization)
    if not token:
        raise AppException(
            code="UNAUTHORIZED",
            message="로그인이 필요해요.",
            status_code=401,
        )

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


async def get_current_user_optional(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict | None:
    """
    개발/실험 환경에서 비로그인 요청을 허용하기 위한 optional 사용자 조회
    """
    if not _extract_token(request, authorization):
        return None
    return await get_current_user(request=request, authorization=authorization)
