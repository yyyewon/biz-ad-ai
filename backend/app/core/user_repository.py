"""
users 테이블 조회/생성 모듈
"""
from __future__ import annotations

from app.core.database import get_connection


def get_or_create_user(
    provider: str,
    provider_user_id: str,
    email: str | None,
    nickname: str | None,
) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE provider = ? AND provider_user_id = ?",
            (provider, provider_user_id),
        ).fetchone()
        if row:
            return dict(row)

        cur = conn.execute(
            "INSERT INTO users (provider, provider_user_id, email, nickname) VALUES (?, ?, ?, ?)",
            (provider, provider_user_id, email, nickname),
        )
        conn.commit()
        new_row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(new_row)
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_user_business_info(
    user_id: int,
    store_name: str | None,
    store_location: str | None,
) -> None:
    """
    유저가 마지막으로 입력한 가게 이름/위치를 저장한다.
    다음 생성 화면에서 자동 입력되며, 유저가 값을 바꾸면 여기서 업데이트된다.
    빈 문자열은 빈 문자열 그대로 저장한다(과거 값을 지우는 의도).
    """
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET store_name = ?, store_location = ? WHERE id = ?",
            ((store_name or "").strip(), (store_location or "").strip(), user_id),
        )
        conn.commit()
    finally:
        conn.close()
