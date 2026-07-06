"""
SQLite 연결 및 스키마 초기화 모듈
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# parents[0] = backend/app/core
# parents[1] = backend/app
# parents[2] = backend
BACKEND_ROOT = Path(__file__).resolve().parents[2]

DB_DIR = BACKEND_ROOT / "data"
DB_PATH = DB_DIR / "app.db"


def get_connection() -> sqlite3.Connection:
    """
    호출할 때마다 새 커넥션을 열고 사용 후 닫기
    """
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """
    서버 시작 시 1회 호출해서 테이블이 없으면 생성
    """
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                provider_user_id TEXT NOT NULL,
                email TEXT,
                nickname TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(provider, provider_user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS generation_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                usage_date TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, usage_date),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
