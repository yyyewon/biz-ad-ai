from __future__ import annotations

from typing import Literal

FoodType = Literal[
    "soup_stew",
    "fried",
    "grilled_bbq",
    "rice_dish",
    "bread_dessert",
    "burger_sandwich",
    "coffee_drink",
]

FOOD_TYPE_LABELS: dict[FoodType, str] = {
    "soup_stew": "국, 찌개",
    "fried": "튀김",
    "grilled_bbq": "구이, 바베큐",
    "rice_dish": "덮밥, 볶음, 비빔",
    "bread_dessert": "빵, 디저트, 케이크",
    "burger_sandwich": "버거, 샌드위치",
    "coffee_drink": "커피, 음료",
}

# 프론트 UI 라벨·내부 코드 모두 허용한다.
FOOD_TYPE_ALIAS_MAP: dict[str, FoodType] = {
    "soup_stew": "soup_stew",
    "fried": "fried",
    "grilled_bbq": "grilled_bbq",
    "rice_dish": "rice_dish",
    "bread_dessert": "bread_dessert",
    "burger_sandwich": "burger_sandwich",
    "coffee_drink": "coffee_drink",
    "국, 찌개": "soup_stew",
    "국,찌개": "soup_stew",
    "국찌개": "soup_stew",
    "튀김": "fried",
    "구이, 바베큐": "grilled_bbq",
    "구이,바베큐": "grilled_bbq",
    "구이바베큐": "grilled_bbq",
    "구이": "grilled_bbq",
    "바베큐": "grilled_bbq",
    "덮밥, 볶음, 비빔": "rice_dish",
    "덮밥,볶음,비빔": "rice_dish",
    "덮밥볶음비빔": "rice_dish",
    "빵, 디저트, 케이크": "bread_dessert",
    "빵,디저트,케이크": "bread_dessert",
    "빵디저트케이크": "bread_dessert",
    "버거, 샌드위치": "burger_sandwich",
    "버거,샌드위치": "burger_sandwich",
    "버거샌드위치": "burger_sandwich",
    "커피, 음료": "coffee_drink",
    "커피,음료": "coffee_drink",
    "커피음료": "coffee_drink",
}


def resolve_food_type(raw: str | None) -> FoodType:
    """
    UI 라벨 또는 내부 코드를 FoodType으로 변환한다.

    Raises:
        ValueError: 지원하지 않는 값이면 발생
    """

    if raw is None or not str(raw).strip():
        raise ValueError("음식 유형이 비어 있습니다.")

    normalized_key = str(raw).strip()
    compact_key = normalized_key.replace(" ", "")

    resolved = FOOD_TYPE_ALIAS_MAP.get(normalized_key) or FOOD_TYPE_ALIAS_MAP.get(compact_key)
    if not resolved:
        raise ValueError(f"지원하지 않는 음식 유형입니다: {raw}")

    return resolved
