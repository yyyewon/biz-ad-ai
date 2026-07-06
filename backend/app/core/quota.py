"""
사용자별 일일 생성 횟수 제한 모듈
"""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from starlette.concurrency import run_in_threadpool

from app.core.database import get_connection
from app.core.exceptions import AppException

KST = ZoneInfo("Asia/Seoul")
DAILY_LIMIT = int(os.getenv("DAILY_GENERATION_LIMIT", "3"))


def _today_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def check_and_increment_daily_usage(user_id: int) -> int:
    """
    오늘 생성 횟수를 확인하고, 한도 내이면 카운트 1 증가
    """
    today = _today_str()
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT count FROM generation_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, today),
        ).fetchone()
        current = row["count"] if row else 0

        if current >= DAILY_LIMIT:
            conn.rollback()
            raise AppException(
                code="DAILY_LIMIT_EXCEEDED",
                message=f"하루 생성 가능 횟수({DAILY_LIMIT}회)를 모두 사용했어요. 내일 다시 시도해 주세요.",
                status_code=429,
                detail={"daily_limit": DAILY_LIMIT, "used": current},
            )

        if row:
            conn.execute(
                "UPDATE generation_usage SET count = count + 1 WHERE user_id = ? AND usage_date = ?",
                (user_id, today),
            )
        else:
            conn.execute(
                "INSERT INTO generation_usage (user_id, usage_date, count) VALUES (?, ?, 1)",
                (user_id, today),
            )
        conn.commit()
        return current + 1
    finally:
        conn.close()


def get_daily_usage(user_id: int) -> dict:
    today = _today_str()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT count FROM generation_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, today),
        ).fetchone()
        used = row["count"] if row else 0
        return {
            "date": today,
            "used": used,
            "limit": DAILY_LIMIT,
            "remaining": max(DAILY_LIMIT - used, 0),
        }
    finally:
        conn.close()

def reset_daily_usage(user_id: int) -> None:
    """
    테스트용: 오늘 사용량 기록을 삭제해 할당량 초기화
    """
    today = _today_str()
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM generation_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, today),
        )
        conn.commit()
    finally:
        conn.close()


async def check_and_increment_daily_usage_async(user_id: int) -> int:
    return await run_in_threadpool(check_and_increment_daily_usage, user_id)


async def get_daily_usage_async(user_id: int) -> dict:
    return await run_in_threadpool(get_daily_usage, user_id)


async def reset_daily_usage_async(user_id: int) -> None:
    return await run_in_threadpool(reset_daily_usage, user_id)