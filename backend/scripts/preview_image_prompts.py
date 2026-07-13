#!/usr/bin/env python
"""
음식 유형 × 출력 유형 프롬프트 미리보기 스크립트.

프론트/API 없이 프롬프트 문구만 확인할 때 사용한다.

예시:
    cd backend
    python scripts/preview_image_prompts.py
    python scripts/preview_image_prompts.py --food-type 국, 찌개 --variant poster
    python scripts/preview_image_prompts.py --only-custom
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.food_type import resolve_food_type
from app.schemas.image_ad import ImageVariantType
from app.services.pipelines.prompt_preview import format_prompt_preview, iter_prompt_previews


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="이미지 생성 프롬프트 미리보기")
    parser.add_argument(
        "--food-type",
        help="음식 유형 (UI 라벨 또는 내부 코드). 예: 국, 찌개 / fried",
    )
    parser.add_argument(
        "--variant",
        choices=["poster", "studio", "instagram_feed"],
        help="출력 유형",
    )
    parser.add_argument(
        "--only-custom",
        action="store_true",
        help="커스텀 템플릿이 채워진 조합만 출력",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    rows = iter_prompt_previews()

    if args.food_type:
        food_type = resolve_food_type(args.food_type)
        rows = [row for row in rows if row[0] == food_type]

    if args.variant:
        rows = [row for row in rows if row[1] == args.variant]

    if args.only_custom:
        rows = [row for row in rows if row[3]]

    if not rows:
        print("출력할 프롬프트 조합이 없습니다.")
        return 1

    blocks = [
        format_prompt_preview(food_type, variant, prompt, uses_template=uses_template)
        for food_type, variant, prompt, uses_template in rows
    ]
    print("\n".join(blocks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
