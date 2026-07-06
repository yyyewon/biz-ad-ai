"""
소셜 로그인(Kakao) API
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from loguru import logger

from app.core.auth_settings import auth_settings
from app.core.deps import get_current_user
from app.core.exceptions import AppException
from app.core.oauth import build_kakao_login_url, exchange_kakao_code
from app.core.quota import get_daily_usage_async, reset_daily_usage_async
from app.core.security import create_access_token
from app.core.user_repository import get_or_create_user
from app.schemas.common import success_response

router = APIRouter()


@router.get("/kakao/login")
async def kakao_login():
    state = secrets.token_urlsafe(16)
    return RedirectResponse(build_kakao_login_url(state))


@router.get("/kakao/callback")
async def kakao_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error or not code:
        raise AppException(
            code="KAKAO_LOGIN_FAILED",
            message="카카오 로그인이 취소되었거나 실패했어요.",
            status_code=400,
            detail={"error": error},
        )

    profile = await exchange_kakao_code(code)
    kakao_account = profile.get("kakao_account", {})
    user = get_or_create_user(
        provider="kakao",
        provider_user_id=str(profile["id"]),
        email=kakao_account.get("email"),
        nickname=(kakao_account.get("profile") or {}).get("nickname"),
    )
    token = create_access_token(user_id=user["id"], provider="kakao")
    logger.info("social_login_success | provider=kakao | user_id={}", user["id"])

    return RedirectResponse(f"{auth_settings.frontend_base_url}/?login_token={token}")


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    usage = await get_daily_usage_async(current_user["id"])
    return success_response(
        data={
            "id": current_user["id"],
            "provider": current_user["provider"],
            "email": current_user["email"],
            "nickname": current_user["nickname"],
            "daily_usage": usage,
        }
    )


@router.post("/dev/reset-quota")
async def dev_reset_quota(current_user: dict = Depends(get_current_user)):
    """
    테스트/데모용: 오늘 생성 횟수 초기화
    """
    if not auth_settings.dev_tools_enabled:
        raise AppException(
            code="DEV_TOOLS_DISABLED",
            message="개발자 도구가 비활성화되어 있어요.",
            status_code=403,
        )

    await reset_daily_usage_async(current_user["id"])
    usage = await get_daily_usage_async(current_user["id"])

    logger.info("dev_reset_quota | user_id={}", current_user["id"])

    return success_response(data={"daily_usage": usage})