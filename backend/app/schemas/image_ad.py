from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.food_type import FoodType, resolve_food_type


GenerationMode = Literal["direct_poster", "two_stage"]
ImageVariantType = Literal["poster", "studio", "instagram_feed"]

DEFAULT_IMAGE_VARIANTS: tuple[ImageVariantType, ...] = (
    "studio",
    "poster",
    "instagram_feed",
)


class ImageAdRequest(BaseModel):
    """
    이미지 광고 생성 요청 schema.

    메모리 기반 처리 기준:
    - 통합 생성 API에서는 UploadFile.read()로 받은 bytes를 pipeline에 직접 전달한다.
    - 단독 이미지 API에서 필요하면 input_image_base64를 사용할 수 있다.
    - input_image_path/image_path는 이전 구조 호환용으로만 남겨둔다.
    """

    model_config = ConfigDict(extra="allow")

    input_image_path: Optional[str] = Field(
        default=None,
        description="이전 파일 저장 방식 호환용 이미지 경로. 신규 로직에서는 사용하지 않는다.",
    )
    image_path: Optional[str] = Field(
        default=None,
        description="이전 input_image_path 별칭. 신규 로직에서는 사용하지 않는다.",
    )
    input_image_base64: Optional[str] = Field(
        default=None,
        description="단독 이미지 생성 API에서 사용할 수 있는 입력 이미지 base64 문자열",
    )

    prompt: Optional[str] = Field(default=None, description="추가 프롬프트 문구(선택)")
    num_images: int = Field(default=3, ge=1, le=6, description="생성할 이미지 개수")
    seed: Optional[int] = Field(default=None, description="재현성을 위한 시드값(선택)")

    store_name: Optional[str] = Field(default=None, description="가게명 메타데이터")
    store_location: Optional[str] = Field(default=None, description="가게 위치/지역 메타데이터")
    menu_name: Optional[str] = Field(default=None, description="메뉴명 메타데이터")
    food_type: Optional[FoodType] = Field(default=None, description="음식 유형")
    promotion_goal: Optional[str] = Field(default=None, description="홍보 목적 메타데이터")
    tone: Optional[str] = Field(default=None, description="문체/톤 메타데이터")
    extra_notes: Optional[str] = Field(
        default=None,
        description="이미지 생성 추가 요청사항 (UI image_request)",
    )
    headline: Optional[str] = Field(default=None, description="포스터 상단 문구")
    price_text: Optional[str] = Field(default=None, description="포스터 가격 문구")
    layout_type: Optional[str] = Field(
        default=None,
        description="(레거시) 포스터 레이아웃 타입. 신규 생성은 image variant(poster/studio/instagram_feed) 기준",
    )
    generation_mode: GenerationMode = Field(
        default="direct_poster",
        description="생성 모드(direct_poster: 원본 사진 기반, two_stage: 중간 음식 이미지 후 포스터)",
    )

    @field_validator("food_type", mode="before")
    @classmethod
    def normalize_food_type(cls, value: object) -> FoodType | None:
        if value is None or value == "":
            return None
        return resolve_food_type(str(value))

    @model_validator(mode="after")
    def normalize_values(self) -> "ImageAdRequest":
        if not self.input_image_path and self.image_path:
            self.input_image_path = self.image_path
        return self


class GeneratedImageItem(BaseModel):
    """
    이전 파일 경로 기반 응답 호환용 schema.

    신규 메모리 기반 응답에서는 ImageAdResponse.images의 base64 문자열을 사용한다.
    """

    index: int
    image_base64: str = ""
    image_path: Optional[str] = None
    download_url: Optional[str] = None


class ImageAdResponse(BaseModel):
    """
    이미지 광고 생성 응답 schema.

    images/poster_images/composite_images/background_images는 모두 base64 문자열 목록이다.
    image_bytes_list는 내부 pipeline 전달용이며 API 응답에서는 제외된다.
    """

    request_id: str
    prompt_used: str
    num_images: int
    latency_ms: int
    generation_mode: GenerationMode = "direct_poster"
    stage_latencies_ms: dict[str, int] = Field(default_factory=dict)

    images: List[str] = Field(default_factory=list, description="최종 포스터 이미지 base64 목록")
    background_images: List[str] = Field(default_factory=list)
    composite_images: List[str] = Field(default_factory=list)
    poster_images: List[str] = Field(default_factory=list)

    image_bytes_list: List[bytes] = Field(default_factory=list, exclude=True)
    applied_variants: List[ImageVariantType] = Field(
        default_factory=list,
        description="생성된 이미지 유형 순서(studio, poster, instagram_feed)",
    )
    food_type: Optional[FoodType] = Field(default=None, description="적용된 음식 유형")

    seed: Optional[int] = None
    message: str = "ok"
