"""
Kakao OAuth Authorization Code Flow 처리 모듈
"""
from __future__ import annotations

import httpx

from app.core.auth_settings import auth_settings
from app.core.exceptions import AppException

KAKAO_AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_USERINFO_URL = "https://kapi.kakao.com/v2/user/me"


def build_kakao_login_url(state: str) -> str:
    url = httpx.URL(
        KAKAO_AUTH_URL,
        params={
            "client_id": auth_settings.kakao_client_id,
            "redirect_uri": auth_settings.kakao_redirect_uri,
            "response_type": "code",
            "state": state,
        },
    )
    return str(url)


async def exchange_kakao_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_res = await client.post(
            KAKAO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": auth_settings.kakao_client_id,
                "client_secret": auth_settings.kakao_client_secret,
                "redirect_uri": auth_settings.kakao_redirect_uri,
                "code": code,
            },
        )
        if token_res.status_code != 200:
            raise AppException(
                code="KAKAO_LOGIN_FAILED",
                message="카카오 로그인에 실패했어요.",
                status_code=400,
                detail=token_res.text,
            )
        access_token = token_res.json().get("access_token")

        userinfo_res = await client.get(
            KAKAO_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_res.status_code != 200:
            raise AppException(
                code="KAKAO_LOGIN_FAILED",
                message="카카오 사용자 정보를 가져오지 못했어요.",
                status_code=400,
                detail=userinfo_res.text,
            )
        return userinfo_res.json()
