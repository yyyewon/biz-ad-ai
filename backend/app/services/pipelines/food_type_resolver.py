from __future__ import annotations

from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.schemas.food_type import FoodType, resolve_food_type


def require_food_type(raw: str | None) -> FoodType:
    """
    이미지 생성에 필요한 음식 유형을 검증·변환한다.
    """

    if raw is None or not str(raw).strip():
        raise AppException(
            errors.MISSING_FOOD_TYPE,
            detail={"food_type": raw},
        )

    try:
        return resolve_food_type(raw)
    except ValueError as exc:
        raise AppException(
            errors.INVALID_FOOD_TYPE,
            detail={
                "food_type": raw,
                "error": str(exc),
            },
        ) from exc
