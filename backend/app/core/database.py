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


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """
    SQLite는 ADD COLUMN IF NOT EXISTS를 지원하지 않으므로,
    PRAGMA table_info로 컬럼 존재 여부를 확인한 뒤 필요할 때만 ALTER TABLE를 실행한다.
    """
    existing_columns = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing_columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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

        # 기존 users 테이블에 store_name/store_location 컬럼이 없으면 추가.
        # 유저가 마지막으로 입력한 가게 정보를 저장해 다음 생성 시 자동 입력하기 위함.
        _ensure_column(conn, "users", "store_name", "TEXT")
        _ensure_column(conn, "users", "store_location", "TEXT")

        conn.commit()
    finally:
        conn.close()
