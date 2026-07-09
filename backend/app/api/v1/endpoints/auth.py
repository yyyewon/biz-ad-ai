"""
소셜 로그인(Kakao) API
"""
from __future__ import annotations

import secrets
from fastapi import APIRouter, Depends, Response, Request
from fastapi.responses import RedirectResponse
from loguru import logger

from app.core.auth_settings import auth_settings
from app.core.deps import get_current_user
from app.core.exceptions import AppException
from app.core.oauth import build_kakao_login_url, exchange_kakao_code
from app.core.quota import get_daily_usage_async, reset_daily_usage_async
from app.core.security import create_access_token, create_refresh_token, decode_refresh_token
from app.core.user_repository import get_or_create_user
from app.schemas.common import success_response

router = APIRouter()

ACTIVE_REFRESH_TOKENS: dict[int, str] = {}


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
    
    access_token = create_access_token(user_id=user["id"], provider="kakao")
    refresh_token = create_refresh_token(user_id=user["id"], provider="kakao")
    
    ACTIVE_REFRESH_TOKENS[user["id"]] = refresh_token
    logger.info("social_login_success | provider=kakao | user_id={}", user["id"])

    response = RedirectResponse(url=auth_settings.frontend_base_url)
    
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=auth_settings.jwt_expires_seconds
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=14 * 24 * 60 * 60
    )
    return response


@router.post("/refresh")
async def refresh_token_endpoint(request: Request, response: Response):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise AppException(code="REFRESH_TOKEN_MISSING", message="인증 세션이 없습니다.", status_code=401)
        
    payload = decode_refresh_token(refresh_token)
    user_id = int(payload["sub"])
    provider = payload["provider"]
    
    if ACTIVE_REFRESH_TOKENS.get(user_id) != refresh_token:
        raise AppException(code="REVOKED_REFRESH_TOKEN", message="유효하지 않은 인증 세션입니다.", status_code=401)
        
    new_access_token = create_access_token(user_id=user_id, provider=provider)
    new_refresh_token = create_refresh_token(user_id=user_id, provider=provider)
    
    ACTIVE_REFRESH_TOKENS[user_id] = new_refresh_token
    logger.info("token_refresh_success | user_id={}", user_id)
    
    response.set_cookie(
        key="access_token", 
        value=new_access_token, 
        httponly=True, 
        secure=True, 
        samesite="lax",
        max_age=auth_settings.jwt_expires_seconds
    )
    response.set_cookie(
        key="refresh_token", 
        value=new_refresh_token, 
        httponly=True, 
        secure=True, 
        samesite="lax",
        max_age=14 * 24 * 60 * 60
    )
    return success_response(data={"status": "refreshed"})


@router.post("/logout")
async def logout_endpoint(response: Response, current_user: dict = Depends(get_current_user)):
    if current_user["id"] in ACTIVE_REFRESH_TOKENS:
        del ACTIVE_REFRESH_TOKENS[current_user["id"]]
        
    response.delete_cookie(key="access_token")
    response.delete_cookie(key="refresh_token")
    return success_response(data={"status": "logged_out"})


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