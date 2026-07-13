#!/usr/bin/env python3
"""
이미지 오버레이용 폰트 설치 스크립트.

backend/assets/fonts/에 한글 폰트를 내려받는다.

    cd backend
    python scripts/setup_fonts.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.utils.font_registry import (  # noqa: E402
    ensure_fonts_installed,
    list_font_keys,
    list_required_font_keys,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="이미지 오버레이용 폰트를 설치합니다.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="manifest 에 등록된 모든 폰트를 받는다 (기본: 현재 역할에 필요한 폰트만)",
    )
    args = parser.parse_args()

    if args.all:
        paths = ensure_fonts_installed(font_keys=list_font_keys())
    else:
        paths = ensure_fonts_installed()

    print("설치된 폰트:")
    for path in paths:
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
