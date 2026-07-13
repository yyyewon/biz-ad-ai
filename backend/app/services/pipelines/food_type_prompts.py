"""
음식 유형 × 이미지 출력 유형별 프롬프트.

파일 읽는 순서 (= 수정하는 순서):
    0. 전역 공통 (리얼리즘)
    1. 스튜디오 — 공통 → 국·찌개 → 튀김 → 구이·바베큐 → 덮밥 → 디저트 → 버거 → 커피
    2. 포스터   — 공통 → 국·찌개 → (나머지 유형은 아래에 추가)
    3. 릴스     — 전 유형 공통 (음식·배경 보존 + 후처리 자막)
    4. 템플릿 등록 · Public API

테스트:
    cd backend
    python scripts/preview_image_prompts.py --food-type "국, 찌개" --variant studio
"""

from __future__ import annotations

from typing import Callable

from app.schemas.food_type import FOOD_TYPE_LABELS, FoodType
from app.schemas.image_ad import ImageAdRequest, ImageVariantType
from app.utils.poster_taglines import resolve_poster_headline_from_purpose
from app.utils.reels_hooks import resolve_reels_hook_from_purpose

# =============================================================================
# 메타 · fallback 힌트
# =============================================================================

VARIANT_LABELS: dict[ImageVariantType, str] = {
    "studio": "스튜디오",
    "poster": "포스터",
    "instagram_feed": "인스타 릴스",
}

FOOD_TYPE_SCENE_HINTS: dict[FoodType, str] = {
    "soup_stew": (
        "국·찌개류. 식당 스냅을 월넛 나무 테이블 위 에디토리얼 컷으로 바꾸되 메인+반찬 구성은 유지"
    ),
    "fried": (
        "튀김류 음식. 바삭한 식감이 느껴지는 클로즈업, 과한 기름기 없이 선명한 텍스처"
    ),
    "grilled_bbq": (
        "구이·바베큐류. 불판 위 고기의 구운 결·윤기·숯불 분위기를 살린 다크무드 에디토리얼 컷"
    ),
    "rice_dish": (
        "덮밥·볶음·비빔류 음식. 토핑과 밥/면의 층감이 보이는 구도, 색감 대비를 살려 식욕을 자극"
    ),
    "bread_dessert": (
        "빵·디저트·케이크류. 디테일한 크럼/크림/결이 보이도록 부드러운 조명, 카페 디저트 감성"
    ),
    "burger_sandwich": (
        "버거·샌드위치류. 층이 잘 보이는 단면 또는 정면 히어로 샷, 신선한 재료감 강조"
    ),
    "coffee_drink": (
        "커피·음료류. 잔·컵의 형태와 음료 결이 보이도록, 깔끔한 상업 음료 촬영 느낌"
    ),
}

VARIANT_DIRECTION_HINTS: dict[ImageVariantType, str] = {
    "studio": (
        "미디엄 와이드 에디토리얼 푸드 사진. 테이블·배경·음식이 함께 보이게, 클로즈업 금지"
    ),
    "poster": (
        "4:5 세로 메뉴 홍보 포스터. 상단 문구+메뉴명+가격, 하단 실사 음식, 음식에 맞는 디자인 배경"
    ),
    "instagram_feed": (
        "인스타 릴스 감성. 매장 배경 유지 + 메인 음식 클로즈업·줌인"
    ),
}

# =============================================================================
# 0. 전역 공통
# =============================================================================

_REALISM_RULES = """
[리얼리즘 — 실사 푸드 사진 품질 (모든 음식·출력 유형 공통)]
- **실제 카메라로 촬영한 editorial food photography**처럼 보일 것
- 음식 **재질·윤기·결·색감**이 사실적일 것 (뜨거운 메뉴는 자연스러운 김 포함)
- 플라스틱·왁스·CGI·3D 렌더·일러스트·AI 그림체 금지
- 과도한 HDR·네온 색·인위적 필터·뽀샤시 뷰티 필터 금지
- 인위적으로 매끄럽거나 왁스처럼 보이는 가짜 음식 질감 금지
""".strip()

_VISUAL_OVERRIDE_KEYWORDS: tuple[str, ...] = (
    "배경",
    "테이블",
    "조명",
    "분위기",
    "색감",
    "톤",
    "연출",
    "느낌",
    "스타일",
    "밝",
    "어둡",
    "따뜻",
    "차분",
    "미니멀",
    "나무",
    "우드",
    "베이지",
)


def _user_requests_visual_override(extra_notes: str) -> bool:
    text = (extra_notes or "").strip().lower()
    if not text:
        return False
    return any(keyword in text for keyword in _VISUAL_OVERRIDE_KEYWORDS)


def _build_user_priority_block(extra_notes: str) -> str:
    note = (extra_notes or "").strip()
    if not note:
        return ""

    return f"""
[최우선 — 사용자 이미지 요청]
아래 사용자 요청을 **음식 유형 기본 규칙·배경 규칙보다 우선** 적용하세요.
충돌할 때는 사용자 요청을 따르되, 음식 형태·메뉴 구성·한국어 텍스트 규칙·로고·워터마크 금지는 유지하세요.
- 사용자 요청: {note}
""".strip()


# =============================================================================
# 1. 스튜디오 (1번 이미지)
# =============================================================================

# -----------------------------------------------------------------------------
# 1-0. 스튜디오 공통
# -----------------------------------------------------------------------------

_STUDIO_PHOTO_TEMPLATE = """
당신은 배달앱·SNS 전문 푸드 포토그래퍼입니다.
첨부된 [{menu_name}] 사진을 **상업용 에디토리얼 푸드 사진**으로 재촬영한 것처럼 재생성하세요.
가게명: {store_name} | 음식 유형: {food_type_label}

{user_priority_block}

{food_subject_rules}

{studio_scene_rules}

{realism_rules}
""".strip()

_STUDIO_VARIANT_OUTPUT = """
[출력 유형: 스튜디오]
- 상업용 editorial food photography 실사 사진 1장
- 미디엄 와이드 구도 — 음식·테이블·배경이 함께 보이게, 극단적 클로즈업 금지
- 비율: 1:1 정사각
- 글자·로고·워터마크 금지

[톤 & 맥락]
- 홍보 목적: {promotion_goal}
- 말투/분위기: {tone}
""".strip()


def _build_studio_photo_template() -> str:
    return _STUDIO_PHOTO_TEMPLATE + "\n\n" + _STUDIO_VARIANT_OUTPUT


# -----------------------------------------------------------------------------
# 1-1. 국·찌개 (soup_stew)
# -----------------------------------------------------------------------------

_STUDIO_SOUP_STEW_SUBJECT = """
[음식 유지 — 국·찌개]
- 원본에 보이는 메인 뚝배기/냄비와 **모든 반찬 접시**를 함께 유지할 것
- 원본 음식·재료·토핑·반찬 구성은 그대로, 메인만 남기지 말 것
- 원본에 없는 음식·반찬·밥·곁들임을 새로 추가하지 말 것
- 원본 반찬·김치·나물을 삭제·생략·잘라내지 말 것
- 그릇/용기 종류와 개수는 원본과 동일하게 유지할 것
- 뜨거운 찌개/국에서 자연스러운 김(steam) — 과장된 CG 연기 금지
- 국물 빨강은 선명하고 깊게, 두부·김치·뚝배기 질감은 사실적으로
- 플라스틱·왁스처럼 매끈한 가짜 질감 금지
- 공중에 뜬 음식, 잘린 그릇, 중복 접시 금지
""".strip()

_STUDIO_SOUP_STEW_SCENE = """
[스튜디오 배경·조명·구도 — 국·찌개]
- 밝은 식당 테이블·물컵·냅킨·콜벨 등 주변 소품 제거
- **월넛·다크오크 거친 나무 테이블** + 따뜻한 갈색 보케 배경(나무 벽·선반 느낌)
- 테이블(갈색)과 배경(보케) 구분, 완전 검정·void 금지
- 따뜻한 측면 조명이 음식+테이블을 함께 비춤, crushed blacks 금지
- 입력 클로즈업 구도를 따르지 말고 **미디엄 와이드 샷** (50mm, 80~100cm)
- 음식 세트 55~65%, 나무 테이블 여백 35~45%, 상단 1/4에 보케 배경
- 45도 측면 앵글, 메인 전경·반찬 뒤쪽 일렬
- 인물 없음
""".strip()

# -----------------------------------------------------------------------------
# 1-2. 튀김 (fried)
# -----------------------------------------------------------------------------

_STUDIO_FRIED_SUBJECT = """
[음식 유지 — 튀김·치킨]
- 원본 사진의 음식·재료·소스·가니쉬만 그대로 유지할 것
- 원본에 없는 재료, 소스, 소품, 가니쉬는 절대 추가하지 말 것
- 그릇·용기·포장 종류와 개수는 원본과 동일하게 유지할 것
- 음식 구성을 임의로 바꾸거나 업그레이드하지 말 것
- 튀김 겉면의 **바삭한 결·황금빛 튀김옷**이 선명하게 보이도록
- 과한 기름기·눅눅한 질감·플라스틱 같은 가짜 튀김 질감 금지
- 공중에 뜬 음식, 잘린 용기 금지
""".strip()

_STUDIO_FRIED_SCENE = """
[스튜디오 배경·조명·구도 — 튀김·치킨]
- 식당 테이블·물컵·냅킨·콜벨 등 주변 소품 제거
- **거친 나무 도마** 또는 **크래프트 페이퍼** 위에 원본 그릇 그대로 배치
- 배경은 단순하고 사람 없음, 캐주얼하지만 식욕을 자극하는 분위기
- 따뜻한 **측면 조명**으로 튀김 겉바삭함·표면 광택 강조
- 입력 클로즈업을 따르지 말고 **미디엄 와이드 샷** (50mm, 80~100cm)
- 음식 55~65%, 테이블/도마 여백 35~45%
- 45도 사이드 앵글 또는 살짝 위에서 내려다본 각도
- 인물 없음
""".strip()

# -----------------------------------------------------------------------------
# 1-3. 구이·바베큐 (grilled_bbq) — 페이히어 타입 C
# -----------------------------------------------------------------------------

_STUDIO_GRILLED_BBQ_SUBJECT = """
[음식 유지 — 구이·바베큐]
- 원본 사진의 고기·재료·곁들임만 그대로 유지할 것
- 원본에 없는 쌈채소, 마늘, 소품, 가니쉬는 절대 추가하지 말 것
- 그릇·불판·철판·용기 종류와 개수는 원본과 동일하게 유지할 것
- 음식 구성을 임의로 바꾸거나 업그레이드하지 말 것
- 고기 표면의 **구운 결·그릴 마크·윤기·불맛**이 선명하게 보이도록
- 고기 단면·겉면의 **육즙감**이 느껴지게, 탄 고기·가짜 플라스틱 질감 금지
- 철판 가장자리 **자연스러운 연기·수증기** — 과장된 CG 연기 금지
- 공중에 뜬 고기, 잘린 불판 금지
""".strip()

_STUDIO_GRILLED_BBQ_SCENE = """
[스튜디오 배경·조명·구도 — 구이·바베큐]
- 식당 테이블·물컵·냅킨·콜벨 등 주변 소품 제거
- **철판·불판·주물 그릴 팬** 위에 원본 고기 그대로 배치 (구이집 불판 느낌 유지)
- 배경은 단순하고 사람 없음, 활기차고 풍성한 **한식 구이·바베큐** 분위기
- **다크무드 + 웜톤** 배경(숯불·갈색·딥 브라운 보케), 완전 검정·void 금지
- 따뜻하고 **강한 측면 조명**으로 고기 표면 광택·그릴 마크·불맛 강조
- 입력 클로즈업을 따르지 말고 **미디엄 와이드 샷** (50mm, 80~100cm)
- 45도 사이드 앵글, **고기와 불판이 함께** 프레임에 들어오도록
- 고기 붉은색과 구운 갈색이 **대비**되게, 과도한 필터 없이 본연 색감 유지
- 인물 없음
""".strip()

# -----------------------------------------------------------------------------
# 1-4. 덮밥·볶음·비빔 (rice_dish)
# -----------------------------------------------------------------------------

_STUDIO_RICE_DISH_SUBJECT = """
[음식 유지 — 덮밥·볶음·비빔]
- 원본 사진의 재료·토핑·소스·밥/면 구성만 그대로 유지할 것
- 원본에 없는 재료, 소품, 가니쉬는 절대 추가하지 말 것
- 그릇·용기 종류와 개수는 원본과 동일하게 유지할 것
- 음식 구성을 임의로 바꾸거나 업그레이드하지 말 것
- 토핑·밥/면 **층감과 색 대비**가 한눈에 보이도록
- 눅눅하거나 색이 죽은 비빔밥·볶음밥 느낌 금지
- 공중에 뜬 음식, 잘린 그릇 금지
""".strip()

_STUDIO_RICE_DISH_SCENE = """
[스튜디오 배경·조명·구도 — 덮밥·볶음·비빔]
- 식당 테이블·물컵·냅킨 등 주변 소품 제거
- **밝은 크림·라이트 그레이 단색 배경** 위에 원본 그릇 그대로 배치
- 배경은 단순하고 사람 없음, 캐주얼하고 깔끔한 분위기
- **균일한 소프트 스튜디오 조명**으로 재료 색감이 선명하게
- 입력 클로즈업을 따르지 말고 **미디엄 와이드 샷** (50mm, 80~100cm)
- 탑다운(정면 위) 또는 살짝 기울인 각도, 재료 배치가 한눈에 보이게
- 그릇 전체가 프레임 안에 들어오도록
- 인물 없음
""".strip()

# -----------------------------------------------------------------------------
# 1-5. 빵·디저트·케이크 (bread_dessert)
# -----------------------------------------------------------------------------

_STUDIO_BREAD_DESSERT_SUBJECT = """
[음식 유지 — 빵·디저트·케이크]
- 원본 사진의 디저트·토핑·데코레이션만 그대로 유지할 것
- 원본에 없는 베리, 허브, 파우더슈가, 장식은 절대 추가하지 말 것
- 그릇·접시 종류와 개수는 원본과 동일하게 유지할 것
- 음식 구성을 임의로 바꾸거나 업그레이드하지 말 것
- **크럼·크림·글레이즈·단면 레이어** 질감이 선명하게 보이도록
- 플라스틱·왁스 같은 가짜 디저트 질감 금지
- 공중에 뜬 음식, 잘린 접시 금지
""".strip()

_STUDIO_BREAD_DESSERT_SCENE = """
[스튜디오 배경·조명·구도 — 빵·디저트·케이크]
- 식당 테이블·물컵 등 주변 소품 제거
- **밝은 대리석** 또는 **린넨 천** 위에 원본 그대로 배치
- 배경은 단순하고 사람 없음, 감성적인 카페 디저트 분위기
- **부드러운 아침 창문광** 또는 확산 스튜디오 조명
- 크림·글레이즈 표면 광택과 단면 레이어가 살아나도록
- 45도 사이드 앵글로 높이·단면 강조, **미디엄 와이드 샷** (50mm)
- 디저트 전체가 프레임 안에 들어오도록
- 인물 없음
""".strip()

# -----------------------------------------------------------------------------
# 1-6. 버거·샌드위치 (burger_sandwich)
# -----------------------------------------------------------------------------

_STUDIO_BURGER_SANDWICH_SUBJECT = """
[음식 유지 — 버거·샌드위치]
- 원본 사진의 재료·소스·사이드만 그대로 유지할 것
- 원본에 없는 감자튀김, 피클, 소스 컵 등은 절대 추가하지 말 것
- 그릇·포장·트레이 종류와 개수는 원본과 동일하게 유지할 것
- 음식 구성을 임의로 바꾸거나 업그레이드하지 말 것
- **번·패티·채소·소스 층**이 선명하게 보이도록
- 눅눅하거나 무너진 버거·샌드위치 느낌 금지
- 공중에 뜬 음식, 잘린 포장 금지
""".strip()

_STUDIO_BURGER_SANDWICH_SCENE = """
[스튜디오 배경·조명·구도 — 버거·샌드위치]
- 식당 테이블·물컵·냅킨 등 주변 소품 제거
- **크래프트 페이퍼** 또는 **슬레이트 보드** 위에 원본 그대로 배치
- 배경은 단순하고 사람 없음, 캐주얼하고 에너지 넘치는 분위기
- 따뜻한 **측면 조명**으로 단면 레이어 입체감·번 윤기·소스 광택 강조
- 정면 또는 약간 사이드 **눈높이 앵글**, 단면 레이어가 모두 보이게
- **미디엄 와이드 샷** (50mm) — 극단적 클로즈업 금지
- 인물 없음
""".strip()

# -----------------------------------------------------------------------------
# 1-7. 커피·음료 (coffee_drink)
# -----------------------------------------------------------------------------

_STUDIO_COFFEE_DRINK_SUBJECT = """
[음식 유지 — 커피·음료]
- 원본 사진의 음료·컵·빨대·토핑·레이어만 그대로 유지할 것
- 원본에 없는 소품, 가니쉬, 과일 슬라이스 등은 절대 추가하지 말 것
- 컵·잔 종류와 개수는 원본과 동일하게 유지할 것
- 음료 구성(레이어, 색상)을 임의로 바꾸거나 업그레이드하지 말 것
- **컵 표면 응결·음료 레이어·거품/크림 결**이 선명하게 보이도록
- 플라스틱·CG 같은 가짜 음료 질감 금지
- 공중에 뜬 컵, 잘린 잔 금지
""".strip()

_STUDIO_COFFEE_DRINK_SCENE = """
[스튜디오 배경·조명·구도 — 커피·음료]
- 식당 테이블·물컵 등 주변 소품 제거
- **밝은 오크** 또는 **화이트 테이블** 위에 원본 컵 그대로 배치
- 배경은 단순하고 사람 없음, 차분하고 깔끔한 미니멀 카페 분위기
- **밝고 부드러운 확산 창문광** 또는 확산 스튜디오 조명
- 컵 표면 응결·음료 레이어·색감 대비가 선명하게
- 중앙 정면 또는 약간 사이드 앵글, 컵 전체가 프레임 안에 들어오도록
- **미디엄 와이드 샷** (50mm)
- 인물 없음
""".strip()

# -----------------------------------------------------------------------------
# 1-x. 스튜디오 레지스트리 (UI 선택 순서)
# -----------------------------------------------------------------------------

FOOD_STUDIO_SUBJECT_RULES: dict[FoodType, str] = {
    "soup_stew": _STUDIO_SOUP_STEW_SUBJECT,
    "fried": _STUDIO_FRIED_SUBJECT,
    "grilled_bbq": _STUDIO_GRILLED_BBQ_SUBJECT,
    "rice_dish": _STUDIO_RICE_DISH_SUBJECT,
    "bread_dessert": _STUDIO_BREAD_DESSERT_SUBJECT,
    "burger_sandwich": _STUDIO_BURGER_SANDWICH_SUBJECT,
    "coffee_drink": _STUDIO_COFFEE_DRINK_SUBJECT,
}

FOOD_STUDIO_SCENE_RULES: dict[FoodType, str] = {
    "soup_stew": _STUDIO_SOUP_STEW_SCENE,
    "fried": _STUDIO_FRIED_SCENE,
    "grilled_bbq": _STUDIO_GRILLED_BBQ_SCENE,
    "rice_dish": _STUDIO_RICE_DISH_SCENE,
    "bread_dessert": _STUDIO_BREAD_DESSERT_SCENE,
    "burger_sandwich": _STUDIO_BURGER_SANDWICH_SCENE,
    "coffee_drink": _STUDIO_COFFEE_DRINK_SCENE,
}


# =============================================================================
# 2. 포스터 (2번 이미지)
# =============================================================================

# -----------------------------------------------------------------------------
# 2-0. 포스터 공통
# -----------------------------------------------------------------------------

_POSTER_LAYOUT_RULES = """
[포스터 구성 — 상업용 메뉴 홍보 레이아웃]
- 비율 4:5 세로 (1024×1536)
- **위에서 아래 순서**, 텍스트는 **상단 가운데 정렬**:
  1. **상단 카피** 1줄 (작은 문구)
  2. **메뉴명** 가장 크고 굵게 (시각적 중심)
  3. **가격** (있을 때만) — 둥근 뱃지·테두리 등 포스터용 디자인
  4. **하단** 메인 음식 실사 히어로 컷 (화면 하단 50~60%)
- 글자색은 배경 톤과 조화되게 (배경보다 약간 진한 같은 계열)
- 텍스트 블록과 음식 영역이 겹치지 않게, 여백·계층 명확히
{store_footer_line}
""".strip()

_POSTER_PHOTO_TEMPLATE = """
당신은 한국 소상공인 **메뉴 홍보 포스터** 디자이너입니다.
첨부 **원본 [{menu_name}] 사진**을 기반으로, 배달앱·식당 SNS에 올릴 **완성형 상업 포스터** 1장을 만드세요.
가게명: {store_name} | 음식 유형: {food_type_label}

{user_priority_block}

{poster_layout_rules}

[텍스트 배치]
- 상단 가운데: 카피(작게) → 메뉴명(가장 크게) → 가격(있을 때, 뱃지)
- 가게명은 하단 우측(있을 때)
- 깔끔한 한국어 고딕체, 음식과 겹치지 않게

{poster_food_rules}

{poster_background_rules}

{realism_rules}

[톤 & 맥락]
- 홍보 목적: {promotion_goal}
- 말투/분위기: {tone}

[명시적 금지]
- 단색·플랫 배경만 있는 포스터
- 스튜디오 식당 테이블 실사 배경 그대로 사용
- 텍스트를 음식 위에 겹치기
- 특정 브랜드 포스터를 그대로 복제
- 위 [반드시 그대로 표기]에 없는 글자·문구 추가
""".strip()

_POSTER_VARIANT_OUTPUT = """
[출력 유형: 포스터]
- 4:5 세로 메뉴 홍보 포스터 비율 (1024×1536)
- 상단 카피·메뉴명·가격·가게명을 포스터 디자인에 포함해 한국어로 직접 표기
""".strip()


def _build_poster_photo_template() -> str:
    return (
        _POSTER_PHOTO_TEMPLATE
        + "\n\n"
        + _POSTER_VARIANT_OUTPUT
        + "\n\n{poster_exact_text_block}"
    )


# -----------------------------------------------------------------------------
# 2-1. 국·찌개 (soup_stew)
# -----------------------------------------------------------------------------

_POSTER_SOUP_STEW_FOOD = """
[음식 — 포스터 히어로 컷 · 국·찌개]
- 첨부 **원본 사진**의 메인 뚝배기/냄비를 기준으로 **실사 editorial food photography**로 재생성
- **메인 메뉴만** 하단 히어로에 크게 배치 (반찬·곁들임 접시는 넣지 말 것)
- 원본 메인 음식·재료·토핑 구성 유지, 원본에 없는 음식 추가 금지
- 자연스러운 김, 국물 윤기·질감 사실적으로
- CGI·일러스트·3D·플라스틱 질감 금지
""".strip()

_POSTER_SOUP_STEW_BACKGROUND = """
[배경·디자인 — 국·찌개 포스터]
- **단색·플랫 컬러만 있는 배경 금지** — 상업용 메뉴 포스터처럼 **디자인된 배경**으로 완성할 것
- 국·찌개에 어울리는 **따뜻한 톤**: 나무·돌·한지 질감, 은은한 전통 문양·패턴, 김·따뜻함을 연상시키는 연출
- 배경은 음식과 **색감이 조화**되게 (뜨거운 찌개 → warm cream·terracotta·deep brown 계열)
- 상단 텍스트 영역과 하단 음식 영역이 **한 장의 포스터**로 자연스럽게 이어지게
- 스튜디오용 나무 테이블·보케 식당 실사 배경 그대로 쓰지 말 것
- 과한 클립아트·저해상도 템플릿 티 금지
- 반찬·곁들임 접시 포함 금지 (메인만)
""".strip()

# -----------------------------------------------------------------------------
# 2-2. 튀김 (fried)
# -----------------------------------------------------------------------------

_POSTER_FRIED_FOOD = """
[음식 — 포스터 히어로 컷 · 튀김]
- 첨부 **원본 사진**의 메인 튀김/치킨을 하단 히어로에 크게 배치
- **바삭한 튀김옷·황금빛 겉면**이 선명하게 보이도록
- 원본 음식·소스·가니쉬 구성 유지, 원본에 없는 음식 추가 금지
- 눅눅하거나 과한 기름기·플라스틱 질감 금지
""".strip()

_POSTER_FRIED_BACKGROUND = """
[배경·디자인 — 튀김 포스터]
- 단색·플랫 배경만 금지 — **캐주얼 다이닝 포스터** 느낌의 디자인 배경
- 크래프트 페이퍼·나무 질감·따뜻한 오렌지·골드 계열 패턴
- 바삭함을 연상시키는 밝고 식욕 자극적인 톤
- 스튜디오 식당 테이블 실사 배경 그대로 쓰지 말 것
""".strip()

# -----------------------------------------------------------------------------
# 2-3. 구이·바베큐 (grilled_bbq)
# -----------------------------------------------------------------------------

_POSTER_GRILLED_BBQ_FOOD = """
[음식 — 포스터 히어로 컷 · 구이·바베큐]
- 첨부 **원본 사진**의 메인 고기/구이를 하단 히어로에 크게 배치
- **그릴 마크·윤기·구운 결**이 선명한 실사 컷
- 원본 음식·토핑·곁들임 구성 유지, 원본에 없는 음식 추가 금지
""".strip()

_POSTER_GRILLED_BBQ_BACKGROUND = """
[배경·디자인 — 구이·바베큐 포스터]
- 단색·플랫 배경만 금지 — **다크무드 바베큐 포스터** 디자인 배경
- 숯·불꽃·스모크·딥 브라운·차콜 계열 질감·패턴
- 고기 색감과 대비되면서 고급스러운 톤
- 스튜디오 식당 테이블 실사 배경 그대로 쓰지 말 것
""".strip()

# -----------------------------------------------------------------------------
# 2-4. 덮밥·볶음·비빔 (rice_dish)
# -----------------------------------------------------------------------------

_POSTER_RICE_DISH_FOOD = """
[음식 — 포스터 히어로 컷 · 덮밥·볶음·비빔]
- 첨부 **원본 사진**의 메인 그릇을 하단 히어로에 크게 배치
- **밥/면·토핑·소스의 층감**이 보이도록
- 원본 구성 유지, 원본에 없는 재료 추가 금지
""".strip()

_POSTER_RICE_DISH_BACKGROUND = """
[배경·디자인 — 덮밥·볶음·비빔 포스터]
- 단색·플랫 배경만 금지 — 밝고 깔끔한 **한 끼 식사 포스터** 배경
- 우드·라이트 베이지·소프트 패턴, 식욕 자극하는 warm tone
- 음식 색감과 조화되는 밝은 상업 포스터 톤
- 스튜디오 식당 테이블 실사 배경 그대로 쓰지 말 것
""".strip()

# -----------------------------------------------------------------------------
# 2-5. 빵·디저트·케이크 (bread_dessert)
# -----------------------------------------------------------------------------

_POSTER_BREAD_DESSERT_FOOD = """
[음식 — 포스터 히어로 컷 · 빵·디저트]
- 첨부 **원본 사진**의 메인 디저트/빵을 하단 히어로에 크게 배치
- **크럼·크림·결이·토핑 디테일**이 선명하게
- 원본 구성 유지, 원본에 없는 장식 추가 금지
""".strip()

_POSTER_BREAD_DESSERT_BACKGROUND = """
[배경·디자인 — 디저트 포스터]
- 단색·플랫 배경만 금지 — **카페 디저트 포스터** 감성 배경
- 파스텔·크림·라떼 베이지·부드러운 패턴
- 달콤하고 세련된 카페 브랜드 느낌
- 스튜디오 식당 테이블 실사 배경 그대로 쓰지 말 것
""".strip()

# -----------------------------------------------------------------------------
# 2-6. 버거·샌드위치 (burger_sandwich)
# -----------------------------------------------------------------------------

_POSTER_BURGER_SANDWICH_FOOD = """
[음식 — 포스터 히어로 컷 · 버거·샌드위치]
- 첨부 **원본 사진**의 메인 버거/샌드위치를 하단 히어로에 크게 배치
- **재료 층·번·패티·치즈·소스**가 식욕 자극적으로 보이게
- 원본 구성 유지, 원본에 없는 재료 추가 금지
""".strip()

_POSTER_BURGER_SANDWICH_BACKGROUND = """
[배경·디자인 — 버거·샌드위치 포스터]
- 단색·플랫 배경만 금지 — **캐주얼 다이너·브런치 포스터** 배경
- 볼드한 컬러 포인트·모던 패턴·따뜻한 레드·머스타드 계열 포인트 가능
- 패스트푸드·브런치 메뉴판 느낌의 상업 포스터
- 스튜디오 식당 테이블 실사 배경 그대로 쓰지 말 것
""".strip()

# -----------------------------------------------------------------------------
# 2-7. 커피·음료 (coffee_drink)
# -----------------------------------------------------------------------------

_POSTER_COFFEE_DRINK_FOOD = """
[음식 — 포스터 히어로 컷 · 커피·음료]
- 첨부 **원본 사진**의 메인 컵/음료를 하단 히어로에 크게 배치
- **음료 겹·거품·얼음·잔 형태**가 선명하게
- 원본 컵·음료 구성 유지, 원본에 없는 소품 추가 금지
""".strip()

_POSTER_COFFEE_DRINK_BACKGROUND = """
[배경·디자인 — 커피·음료 포스터]
- 단색·플랫 배경만 금지 — **미니멀 카페 음료 포스터** 배경
- 화이트·오크·소프트 그린·클린 패턴, 차분하고 세련된 톤
- 음료 색감이 돋보이는 깔끔한 상업 포스터
- 스튜디오 식당 테이블 실사 배경 그대로 쓰지 말 것
""".strip()

# -----------------------------------------------------------------------------
# 2-x. 포스터 레지스트리 (UI 선택 순서)
# -----------------------------------------------------------------------------

FOOD_POSTER_FOOD_RULES: dict[FoodType, str] = {
    "soup_stew": _POSTER_SOUP_STEW_FOOD,
    "fried": _POSTER_FRIED_FOOD,
    "grilled_bbq": _POSTER_GRILLED_BBQ_FOOD,
    "rice_dish": _POSTER_RICE_DISH_FOOD,
    "bread_dessert": _POSTER_BREAD_DESSERT_FOOD,
    "burger_sandwich": _POSTER_BURGER_SANDWICH_FOOD,
    "coffee_drink": _POSTER_COFFEE_DRINK_FOOD,
}

FOOD_POSTER_BACKGROUND_RULES: dict[FoodType, str] = {
    "soup_stew": _POSTER_SOUP_STEW_BACKGROUND,
    "fried": _POSTER_FRIED_BACKGROUND,
    "grilled_bbq": _POSTER_GRILLED_BBQ_BACKGROUND,
    "rice_dish": _POSTER_RICE_DISH_BACKGROUND,
    "bread_dessert": _POSTER_BREAD_DESSERT_BACKGROUND,
    "burger_sandwich": _POSTER_BURGER_SANDWICH_BACKGROUND,
    "coffee_drink": _POSTER_COFFEE_DRINK_BACKGROUND,
}


# =============================================================================
# 3. 릴스 (3번 이미지 · instagram_feed)
# =============================================================================

# -----------------------------------------------------------------------------
# 3-0. 릴스 공통
# -----------------------------------------------------------------------------

_REELS_PHOTO_TEMPLATE = """
당신은 인스타그램·릴스 **맛집 홍보 영상 썸네일**을 만드는 푸드 크리에이터입니다.
첨부 **매장에서 찍은 [{menu_name}] 사진**을, 릴스에 올릴 **음식 클로즈업 컷** 1장으로 다듬으세요.
가게명: {store_name} | 음식 유형: {food_type_label}

{user_priority_block}

{reels_food_rules}

{reels_scene_rules}

{realism_rules}

{reels_realism_extra}

[톤 & 맥락]
- 홍보 목적: {promotion_goal}
- 말투/분위기: {tone}
""".strip()

_REELS_VARIANT_OUTPUT = """
[출력 유형: 인스타 릴스]
- 9:16 세로 릴스 썸네일 비율 (1024×1536)
- 메인 음식 **극단적 클로즈업**, 매장 배경은 원본 유지·얕은 보케
- **왼쪽 하단 자막 영역은 비워둘 것** — 한국어 후킹 문구는 후처리로 합성
- 재생 버튼·UI 오버레이·글자·워터마크 금지
""".strip()


def _build_reels_photo_template() -> str:
    return _REELS_PHOTO_TEMPLATE + "\n\n" + _REELS_VARIANT_OUTPUT


_REELS_FOOD_RULES = """
[음식 — 릴스 클로즈업 (전 유형 공통)]
- **메인 음식**이 화면의 70~85%를 차지하도록 크게 (극단적 푸드 클로즈업)
- 원본 음식·재료·토핑·색·질감·그릇/용기는 **최대한 그대로** 유지, 원본에 없는 음식·소품 추가 금지
- 원본에 있던 곁들임·반찬은 프레임 가장자리에 일부만 보여도 됨 (메인이 절대 중심)
- 뜨거운 메뉴는 자연스러운 김(steam) 가능 — 과장된 CG 연기 금지
- CGI·일러스트·3D·플라스틱 질감 금지
""".strip()

_REELS_SCENE_RULES = """
[릴스 촬영 — 매장 배경 유지 (전 유형 공통)]
- **원본 매장·식당 배경**(테이블·인테리어·조명·간판·로고)을 **그대로 보존**
- 배경은 얕은 심도(bokeh)로 살짝 흐려도 되지만, **스튜디오 테이블·보케·단색 배경으로 교체 금지**
- 매장 실내 촬영 릴스 느낌: 스마트폰/카메라로 찍은 맛집 릴스 썸네일 톤
- 밝고 선명, 식욕 자극하는 실사 톤 (과한 필터·네온 금지)
- 45도 또는 살짝 위에서 내려다본 각도, 인물 없음
- 재생 버튼·UI 아이콘·워터마크 금지
- **화면 왼쪽 하단 20%는 자막용 여백** — 한국어 후킹 문구는 후처리(PIL)로 합성, 이미지에 글자 넣지 말 것
""".strip()

_REELS_SCENE_RULES_FLEXIBLE = """
[릴스 촬영 — 사용자 배경·연출 요청 반영]
- **원본 음식·재료·토핑·그릇/용기 형태**는 유지
- 상단 **최우선 사용자 요청**에 맞게 배경·조명·분위기·색감·테이블 연출을 조정할 수 있음
- 메인 음식 **극단적 클로즈업**(화면 70~85%), 인물 없음
- 밝고 선명한 실사 톤, 재생 버튼·UI·워터마크·이미지 내 글자 금지
- **화면 왼쪽 하단 20%는 자막용 여백** — 후킹 문구는 후처리(PIL)로 합성
""".strip()


def _build_reels_scene_rules(extra_notes: str) -> str:
    if _user_requests_visual_override(extra_notes):
        return _REELS_SCENE_RULES_FLEXIBLE
    return _REELS_SCENE_RULES


_REELS_REALISM_EXTRA = """
[리얼리즘 — 릴스 추가 강조 (위 공통 규칙 + 아래를 더 엄격히)]
- **실제 맛집에서 스마트폰·카메라로 찍은 한 컷**처럼 보일 것 — 스튜디오 재촬영·합성·AI 리터치 티 금지
- 극단적 클로즈업에서도 **기공·결·윤기·그릴 마크·소스 맺힘·국물 표면** 등 미세 질감이 선명할 것
- 매장 조명·색온도·배경은 원본과 **같은 장소·같은 촬영**에서 이어진 것처럼 자연스러울 것
- 음식만 유독 선명하고 배경이 따로 붙인 합성처럼 보이면 실패
- 인위적 뽀샤시·피부보정식 스무딩·과선명·가짜 보케·양감 왜곡 금지
- 릴스 썸네일이어도 **실사 맛집 사진** 퀄리티 — 일러스트·3D·광고 CG 느낌 절대 금지
""".strip()


# =============================================================================
# 4. 템플릿 등록 — (food_type, variant)
# =============================================================================

_STUDIO_TEMPLATE = _build_studio_photo_template()
_POSTER_TEMPLATE = _build_poster_photo_template()
_REELS_TEMPLATE = _build_reels_photo_template()

FOOD_VARIANT_PROMPT_TEMPLATES: dict[tuple[FoodType, ImageVariantType], str] = {
    # --- 스튜디오 (유형별 규칙) ---
    ("soup_stew", "studio"): _STUDIO_TEMPLATE,
    ("fried", "studio"): _STUDIO_TEMPLATE,
    ("grilled_bbq", "studio"): _STUDIO_TEMPLATE,
    ("rice_dish", "studio"): _STUDIO_TEMPLATE,
    ("bread_dessert", "studio"): _STUDIO_TEMPLATE,
    ("burger_sandwich", "studio"): _STUDIO_TEMPLATE,
    ("coffee_drink", "studio"): _STUDIO_TEMPLATE,
    # --- 포스터 (유형별 규칙) ---
    **{
        (food_type, "poster"): _POSTER_TEMPLATE
        for food_type in FOOD_STUDIO_SUBJECT_RULES
    },
    # --- 릴스 (전 유형 공통 템플릿) ---
    **{
        (food_type, "instagram_feed"): _REELS_TEMPLATE
        for food_type in FOOD_STUDIO_SUBJECT_RULES
    },
}


# =============================================================================
# Public API
# =============================================================================


def _build_reels_hook_line(
    *,
    store_name: str,
    menu_name: str,
    store_location: str = "",
    promotion_goal: str,
    price_text: str = "",
) -> str:
    hook = resolve_reels_hook_from_purpose(
        promotion_goal,
        store_name=store_name,
        menu_name=menu_name,
        store_location=store_location,
        price_text=price_text,
    )
    return f"- **후킹 문구 (하단 자막으로 표기)**: {hook}"


def build_poster_exact_text_block(
    *,
    headline: str,
    menu_name: str,
    price_text: str = "",
    store_name: str = "",
) -> str:
    """포스터 프롬프트 맨 끝에 붙이는 정확 표기 문구 블록."""

    menu = (menu_name or "").strip() or "오늘의 메뉴"
    items: list[str] = []
    index = 1

    head = (headline or "").strip()
    if head:
        items.append(f'{index}. "{head}" — 상단 카피 (작게)')
        index += 1

    items.append(f'{index}. "{menu}" — 메뉴명 (가장 크고 굵게)')
    index += 1

    price = (price_text or "").strip()
    if price:
        items.append(f'{index}. "{price}" — 가격 (뱃지/테두리 안)')
        index += 1

    store = (store_name or "").strip()
    if store:
        items.append(f'{index}. "{store}" — 하단 우측 가게명 (작게)')

    numbered = "\n".join(items)
    return f"""
[반드시 그대로 표기 — 최우선]
아래 문구만 이미지에 넣을 것. 오타·누락·추가 글자·영문·해시태그·로고 금지.
띄어쓰기·숫자·₩/원 기호까지 아래와 **완전히 동일**하게.
{numbered}
""".strip()


def _build_poster_headline_line(*, headline: str, store_name: str) -> str:
    _ = store_name
    if headline:
        return f"- **상단 카피**: {headline}"
    return ""


def _build_poster_price_lines(price_text: str) -> tuple[str, str]:
    if price_text:
        return (
            f"- **가격 표기 (뱃지/테두리 디자인 안에)**: {price_text}",
            "- 가격은 띄어쓰기·숫자·₩/원 기호까지 위 표기와 정확히 동일하게",
        )
    return ("- 가격 문구는 넣지 말 것", "")


def _build_poster_store_footer_line(
    store_name: str,
    store_location: str = "",
) -> str:
    lines: list[str] = []
    location = (store_location or "").strip()
    name = (store_name or "").strip()

    if name:
        lines.append(f"- **하단 가게명 (작게, 우측 하단 정렬)**: {name}")
    if location:
        lines.append(f"- 배경 톤 참고: 매장 위치 맥락 {location}")
    return "\n".join(lines)


def _lookup_food_rules(registry: dict[FoodType, str], food_type: FoodType) -> str:
    return registry.get(food_type, "")


def uses_custom_template(food_type: FoodType, variant: ImageVariantType) -> bool:
    template = FOOD_VARIANT_PROMPT_TEMPLATES.get((food_type, variant), "").strip()
    return bool(template)


def get_food_type_scene_hint(food_type: FoodType) -> str:
    return FOOD_TYPE_SCENE_HINTS[food_type]


def get_variant_direction_hint(variant: ImageVariantType) -> str:
    return VARIANT_DIRECTION_HINTS[variant]


def build_template_context(
    payload: ImageAdRequest,
    *,
    food_type: FoodType,
    variant: ImageVariantType,
) -> dict[str, str]:
    store_name = payload.store_name or ""
    store_location = (payload.store_location or "").strip()
    headline = (payload.headline or "").strip()
    if not headline and variant == "poster":
        headline = resolve_poster_headline_from_purpose(payload.promotion_goal or "")
    price_text = (payload.price_text or "").strip()
    extra_notes = (payload.extra_notes or "").strip()
    price_line, price_accuracy_line = _build_poster_price_lines(price_text)
    menu_name = payload.menu_name or "오늘의 메뉴"

    return {
        "store_name": store_name,
        "store_location": store_location,
        "menu_name": menu_name,
        "tone": payload.tone or "",
        "promotion_goal": payload.promotion_goal or "",
        "extra_notes": extra_notes,
        "user_priority_block": _build_user_priority_block(extra_notes),
        "food_type_label": FOOD_TYPE_LABELS[food_type],
        "variant_label": VARIANT_LABELS[variant],
        "scene_hint": get_food_type_scene_hint(food_type),
        "variant_hint": get_variant_direction_hint(variant),
        "headline_line": _build_poster_headline_line(
            headline=headline,
            store_name=store_name,
        ),
        "price_line": price_line,
        "price_accuracy_line": price_accuracy_line,
        "extra_notes_line": "",
        # 스튜디오
        "food_subject_rules": FOOD_STUDIO_SUBJECT_RULES[food_type],
        "studio_scene_rules": FOOD_STUDIO_SCENE_RULES[food_type],
        # 포스터
        "poster_food_rules": _lookup_food_rules(FOOD_POSTER_FOOD_RULES, food_type),
        "poster_background_rules": _lookup_food_rules(
            FOOD_POSTER_BACKGROUND_RULES, food_type
        ),
        "poster_layout_rules": _POSTER_LAYOUT_RULES.format(
            store_footer_line=_build_poster_store_footer_line(
                store_name,
                store_location,
            ),
        ),
        "poster_exact_text_block": build_poster_exact_text_block(
            headline=headline,
            menu_name=menu_name,
            price_text=price_text,
            store_name=store_name,
        ),
        # 릴스 (전 유형 공통)
        "reels_food_rules": _REELS_FOOD_RULES,
        "reels_scene_rules": _build_reels_scene_rules(extra_notes),
        "reels_realism_extra": _REELS_REALISM_EXTRA,
        "reels_hook_line": _build_reels_hook_line(
            store_name=store_name,
            menu_name=payload.menu_name or "",
            store_location=store_location,
            promotion_goal=payload.promotion_goal or "",
            price_text=price_text,
        ),
        # 공통
        "realism_rules": _REALISM_RULES,
    }


def render_food_variant_prompt_template(
    payload: ImageAdRequest,
    *,
    food_type: FoodType,
    variant: ImageVariantType,
) -> str | None:
    template = FOOD_VARIANT_PROMPT_TEMPLATES.get((food_type, variant), "").strip()
    if not template:
        return None

    context = build_template_context(payload, food_type=food_type, variant=variant)
    return template.format(**context)


def build_food_context_line(food_type: FoodType) -> str:
    label = FOOD_TYPE_LABELS[food_type]
    scene_hint = get_food_type_scene_hint(food_type)
    return f"음식 유형: {label}. {scene_hint}"


def build_variant_context_line(variant: ImageVariantType) -> str:
    return f"출력 유형: {get_variant_direction_hint(variant)}"


def append_food_and_variant_context(
    base_prompt: str,
    *,
    food_type: FoodType,
    variant: ImageVariantType,
) -> str:
    return ", ".join(
        [
            base_prompt,
            build_food_context_line(food_type),
            build_variant_context_line(variant),
        ]
    )


def build_food_variant_prompt(
    payload: ImageAdRequest,
    variant: ImageVariantType,
    *,
    food_type: FoodType,
    build_poster_prompt: Callable[[ImageAdRequest, str], str],
) -> str:
    """
    음식 유형 + 출력 유형 프롬프트를 반환한다.

    FOOD_VARIANT_PROMPT_TEMPLATES에 양식이 있으면 그걸 쓰고,
    없으면 기존 포스터 프롬프트 + 힌트 fallback을 사용한다.
    """

    custom_prompt = render_food_variant_prompt_template(
        payload,
        food_type=food_type,
        variant=variant,
    )
    if custom_prompt:
        return custom_prompt

    from app.services.pipelines.image_variant_prompts import VARIANT_LAYOUT_MAP

    layout_type = VARIANT_LAYOUT_MAP[variant]
    base_prompt = build_poster_prompt(payload, layout_type)
    return append_food_and_variant_context(
        base_prompt,
        food_type=food_type,
        variant=variant,
    )


def build_inpaint_food_prompt(payload: ImageAdRequest, food_type: FoodType) -> str:
    return build_food_context_line(food_type)
