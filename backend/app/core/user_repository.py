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
