from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


MoodType = Literal["cozy", "minimal", "luxury", "fresh", "vintage"]
GenerationMode = Literal["direct_poster", "two_stage"]
MOOD_ALIAS_MAP: dict[str, MoodType] = {
    "cozy": "cozy",
    "감성카페": "cozy",
    "카페감성": "cozy",
    "minimal": "minimal",
    "모던미니멀": "minimal",
    "모던 미니멀": "minimal",
    "luxury": "luxury",
    "고급스러운": "luxury",
    "fresh": "fresh",
    "화사한브런치": "fresh",
    "화사한 브런치": "fresh",
    "vintage": "vintage",
    "빈티지레트로": "vintage",
    "빈티지 레트로": "vintage",
}


class ImageAdRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    input_image_path: Optional[str] = Field(
        default=None, description="전경(누끼) 이미지 경로(RGBA 권장)"
    )
    image_path: Optional[str] = Field(
        default=None, description="호환성을 위한 input_image_path 별칭"
    )
    mood: str = Field(default="cozy", description="인스타 무드 프리셋")
    mood_list: Optional[List[str]] = Field(
        default=None,
        description="여러 무드를 순서대로 적용할 때 사용하는 목록(선택)",
    )
    prompt: Optional[str] = Field(default=None, description="추가 프롬프트 문구(선택)")
    num_images: int = Field(default=3, ge=1, le=6, description="생성할 이미지 개수")
    seed: Optional[int] = Field(default=None, description="재현성을 위한 시드값(선택)")
    store_name: Optional[str] = Field(default=None, description="가게명 메타데이터")
    menu_name: Optional[str] = Field(default=None, description="메뉴명 메타데이터")
    promotion_goal: Optional[str] = Field(default=None, description="홍보 목적 메타데이터")
    tone: Optional[str] = Field(default=None, description="문체/톤 메타데이터")
    extra_notes: Optional[str] = Field(default=None, description="추가 요청사항 메타데이터")
    headline: Optional[str] = Field(default=None, description="포스터 상단 문구")
    price_text: Optional[str] = Field(default=None, description="포스터 가격 문구")
    layout_type: Optional[str] = Field(
        default=None,
        description="포스터 레이아웃 타입(예: auto, classic, focus, left)",
    )
    generation_mode: GenerationMode = Field(
        default="direct_poster",
        description="생성 모드(direct_poster: 누끼에서 바로 포스터, two_stage: 중간 음식 이미지 후 포스터)",
    )

    @model_validator(mode="after")
    def validate_input_path(self) -> "ImageAdRequest":
        if not self.input_image_path and self.image_path:
            self.input_image_path = self.image_path
        if not self.input_image_path:
            raise ValueError("input_image_path 값이 필요합니다.")
        normalized = MOOD_ALIAS_MAP.get(self.mood.replace(" ", ""), MOOD_ALIAS_MAP.get(self.mood))
        if not normalized:
            raise ValueError("지원하지 않는 mood 값입니다.")
        self.mood = normalized
        if self.mood_list:
            normalized_list: list[MoodType] = []
            for mood_value in self.mood_list:
                mood_key = mood_value.replace(" ", "")
                mapped = MOOD_ALIAS_MAP.get(mood_key, MOOD_ALIAS_MAP.get(mood_value))
                if not mapped:
                    raise ValueError(f"지원하지 않는 mood_list 값입니다: {mood_value}")
                normalized_list.append(mapped)
            self.mood_list = normalized_list
        return self


class GeneratedImageItem(BaseModel):
    index: int
    image_path: str
    download_url: str


class ImageAdResponse(BaseModel):
    request_id: str
    mood: MoodType
    prompt_used: str
    num_images: int
    latency_ms: int
    generation_mode: GenerationMode = "direct_poster"
    stage_latencies_ms: dict[str, int] = Field(default_factory=dict)
    images: List[GeneratedImageItem]
    background_images: List[GeneratedImageItem] = Field(default_factory=list)
    composite_images: List[GeneratedImageItem] = Field(default_factory=list)
    poster_images: List[GeneratedImageItem] = Field(default_factory=list)
    applied_moods: List[MoodType] = Field(default_factory=list)
    seed: Optional[int] = None
    message: str = "ok"
