import time
import uuid
from pathlib import Path
from typing import Optional
import shutil

from PIL import Image

from app.schemas.image_ad import GenerationMode, GeneratedImageItem, ImageAdRequest, ImageAdResponse
from app.services.providers.factory import get_image_provider


MOOD_INPAINT_STYLE_MAP: dict[str, str] = {
    "cozy": "따뜻한 베이지/우드 계열 색감, 부드러운 자연광, 아늑한 카페 무드",
    "minimal": "밝은 아이보리/그레이 계열 색감, 단순한 배경, 정돈된 미니멀 무드",
    "luxury": "딥 브라운/차콜 계열 색감, 대비가 강한 조명, 고급스러운 럭셔리 무드",
    "fresh": "민트/크림 계열 색감, 밝고 산뜻한 자연광, 청량한 브런치 무드",
    "vintage": "채도 낮은 베이지/브라운 계열 색감, 은은한 필름 질감, 빈티지 레트로 무드",
}

LAYOUT_ALIAS_MAP: dict[str, str] = {
    "auto": "auto",
    "classic": "classic",
    "focus": "focus",
    "left": "left",
    "기본": "classic",
    "기본형": "classic",
    "집중형": "focus",
    "포커스": "focus",
    "좌측형": "left",
    "좌측": "left",
}

LAYOUT_POSTER_GUIDE_MAP: dict[str, str] = {
    "classic": "상단 텍스트, 중앙 가격 포인트, 하단 음식 히어로 이미지의 균형 잡힌 정석형 구도",
    "focus": "타이포를 간결하게 두고 음식을 더 크게 강조하는 집중형 구도",
    "left": "음식을 좌측 또는 좌중앙에 배치하고 텍스트를 우측/상단으로 분산한 비대칭 구도",
}

POSTER_PROMPT_HARD_CONSTRAINTS: list[str] = [
    "반드시 1080x1350 비율의 세로 포스터 디자인으로 생성해줘.",
    "텍스트는 오직 한국어만 사용하고, 임의 영문 문구는 절대 넣지 마.",
    "아래 텍스트 3개를 정확히 동일하게 표기해줘. 띄어쓰기/문장부호/숫자/통화기호를 변경하지 마.",
    "가독성이 낮은 배경 위에 텍스트를 두지 말고, 텍스트 영역은 대비를 충분히 확보해줘.",
    "잘린 텍스트, 깨진 글자, 오탈자, 반복 글자, 의미 없는 문자는 절대 넣지 마.",
    "로고, 워터마크, 브랜드명, 서명, 불필요한 장식 문구를 넣지 마.",
]

POSTER_RETRY_SUFFIXES: list[str] = [
    "",
    "재시도 지시: 텍스트 정확도와 가독성을 최우선으로 다시 생성해줘. 레이아웃은 단순하고 안정적으로 구성해줘.",
    "최종 재시도 지시: 텍스트 3개를 상단/중앙에 명확히 분리 배치하고, 음식은 하단 히어로 컷으로 크게 배치해줘.",
]


def _build_inpaint_prompt(payload: ImageAdRequest, mood: str) -> str:
    base_style = MOOD_INPAINT_STYLE_MAP.get(mood, MOOD_INPAINT_STYLE_MAP["cozy"])
    prompt_chunks = [
        "투명한 배경 영역만 자연스럽게 채워서 광고용 음식 이미지를 만들어줘.",
        base_style,
        "업로드된 음식과 접시는 최대한 유지해줘.",
        "실사 기반의 상업용 푸드 포토그래피 느낌으로 생성해줘.",
        "문구를 넣을 수 있도록 여백이 있는 깔끔한 구도로 만들어줘.",
        "최종 색감/조명 분위기는 반드시 위의 무드 스타일과 일치시켜줘.",
        "이미지 안에 글자, 영문 단어, 메뉴명, 로고, 워터마크를 절대 넣지 마.",
        "추가 음식, 중복 접시, 잘린 접시를 만들지 마.",
    ]
    if payload.promotion_goal:
        prompt_chunks.append(f"홍보 목적 맥락: {payload.promotion_goal}")
    if payload.tone:
        prompt_chunks.append(f"전반적인 무드 톤: {payload.tone}")
    if payload.extra_notes:
        prompt_chunks.append(f"추가 요청사항: {payload.extra_notes}")
    if payload.prompt:
        prompt_chunks.append(f"사용자 직접 프롬프트: {payload.prompt}")
    return ", ".join(prompt_chunks)


def _build_inpaint_mask(source_rgba: Image.Image, mask_path: Path) -> None:
    """
    이미지 편집용 RGBA 마스크를 생성합니다.
    - 주제(음식/접시) 영역: 불투명 알파(보존)
    - 배경 영역: 투명 알파(인페인팅 대상)
    """
    alpha = source_rgba.split()[-1]
    mask = Image.new("RGBA", source_rgba.size, (0, 0, 0, 255))
    mask.putalpha(alpha)
    mask.save(mask_path, format="PNG")


def _resolve_layout_type(layout_type: Optional[str], index: int) -> str:
    if layout_type:
        normalized = LAYOUT_ALIAS_MAP.get(layout_type.strip(), LAYOUT_ALIAS_MAP.get(layout_type.replace(" ", "")))
        if normalized and normalized != "auto":
            return normalized
    # Auto-rotate layouts for multi-image diversity.
    ordered = ["classic", "focus", "left"]
    return ordered[index % len(ordered)]


def _resolve_mood_for_index(payload: ImageAdRequest, index: int) -> str:
    if payload.mood_list:
        return payload.mood_list[index % len(payload.mood_list)]
    return payload.mood


def _resolve_generation_mode(mode: GenerationMode | str | None) -> GenerationMode:
    if mode == "two_stage":
        return "two_stage"
    return "direct_poster"


def _build_poster_prompt(payload: ImageAdRequest, mood: str, layout_type: str) -> str:
    mood_style = MOOD_INPAINT_STYLE_MAP.get(mood, MOOD_INPAINT_STYLE_MAP["cozy"])
    layout_guide = LAYOUT_POSTER_GUIDE_MAP.get(layout_type, LAYOUT_POSTER_GUIDE_MAP["classic"])
    headline = payload.headline or "간편하고 든든한 한끼"
    menu_name = payload.menu_name or "오늘의 메뉴"
    price_text = payload.price_text or "₩14,000"
    prompt_chunks = [
        "입력된 음식 사진을 기반으로 인스타그램용 세로 광고 포스터를 실사 스타일로 만들어줘.",
        f"포스터 무드: {mood_style}",
        f"레이아웃 가이드: {layout_guide}",
        "음식과 접시의 형태/재질은 유지하고 배경, 조명, 구도는 포스터 디자인에 맞게 새롭게 구성해줘.",
        "세련된 브랜드 광고 느낌으로 전체 레이아웃을 새로 디자인해줘. 기존 템플릿처럼 보이지 않게 다양성을 확보해줘.",
        "텍스트를 포스터 안에 직접 넣어줘. 글자 오탈자 없이 정확히 표기해줘.",
        f"표기 텍스트1(상단 카피): {headline}",
        f"표기 텍스트2(메뉴명, 가장 크게): {menu_name}",
        f"표기 텍스트3(가격): {price_text}",
        *POSTER_PROMPT_HARD_CONSTRAINTS,
        "텍스트는 가독성이 높아야 하고 음식을 과도하게 가리지 않게 배치해줘.",
        "로고/워터마크/불필요한 영문 문구는 넣지 마.",
    ]
    if payload.promotion_goal:
        prompt_chunks.append(f"홍보 목적 맥락: {payload.promotion_goal}")
    if payload.tone:
        prompt_chunks.append(f"전반적인 문체/분위기: {payload.tone}")
    if payload.extra_notes:
        prompt_chunks.append(f"추가 요청사항: {payload.extra_notes}")
    if payload.prompt:
        prompt_chunks.append(f"사용자 직접 프롬프트: {payload.prompt}")
    return ", ".join(prompt_chunks)


def _generate_poster_with_retries(
    *,
    provider,
    source_image_path: Path,
    output_dir: Path,
    base_prompt: str,
    mask_image_path: Path | None = None,
) -> list[Path]:
    last_error: Exception | None = None
    for attempt_idx, suffix in enumerate(POSTER_RETRY_SUFFIXES):
        retry_prompt = f"{base_prompt}, {suffix}" if suffix else base_prompt
        try:
            paths = provider.generate(
                input_image_path=source_image_path,
                mask_image_path=mask_image_path,
                prompt=retry_prompt,
                num_images=1,
                output_dir=output_dir / f"attempt_{attempt_idx + 1}",
            )
            if paths:
                return paths
        except Exception as exc:
            last_error = exc
    if last_error:
        raise RuntimeError(f"포스터 생성 재시도 실패: {last_error}") from last_error
    return []


def generate_image_ads(
    payload: ImageAdRequest,
    output_root: Path,
    public_prefix: str = "/outputs",
    seed: Optional[int] = None,
) -> ImageAdResponse:
    started = time.perf_counter()
    request_id = f"img-{uuid.uuid4().hex[:10]}"
    request_output_dir = output_root / request_id
    request_output_dir.mkdir(parents=True, exist_ok=True)

    source_path = Path(payload.input_image_path)
    if not source_path.exists():
        raise FileNotFoundError(f"입력 이미지를 찾을 수 없습니다: {source_path}")

    source_rgba = Image.open(source_path).convert("RGBA")
    prepared_source_path = request_output_dir / "source_rgba.png"
    source_rgba.save(prepared_source_path, format="PNG")
    mask_path = request_output_dir / "inpaint_mask.png"
    _build_inpaint_mask(source_rgba, mask_path)

    provider = get_image_provider()
    generation_mode = _resolve_generation_mode(payload.generation_mode)
    prompt_used = ""
    generated_paths: list[Path] = []
    applied_moods: list[str] = []
    stage_latencies_ms: dict[str, int] = {}

    food_stage_started = time.perf_counter()
    if generation_mode == "two_stage":
        for idx in range(payload.num_images):
            current_mood = _resolve_mood_for_index(payload, idx)
            applied_moods.append(current_mood)
            current_prompt = _build_inpaint_prompt(payload, current_mood)
            if not prompt_used:
                prompt_used = current_prompt

            iter_output_dir = request_output_dir / f"_gen_{idx + 1}"
            iter_paths = provider.generate(
                input_image_path=prepared_source_path,
                mask_image_path=mask_path,
                prompt=current_prompt,
                num_images=1,
                output_dir=iter_output_dir,
            )
            if not iter_paths:
                raise RuntimeError("이미지 생성 결과가 비어 있습니다.")
            final_generated_path = request_output_dir / f"generated_{idx + 1}.png"
            shutil.move(str(iter_paths[0]), str(final_generated_path))
            generated_paths.append(final_generated_path)
    else:
        for idx in range(payload.num_images):
            applied_moods.append(_resolve_mood_for_index(payload, idx))
    stage_latencies_ms["food_generation_ms"] = int((time.perf_counter() - food_stage_started) * 1000)

    generated_items: list[GeneratedImageItem] = []
    poster_items: list[GeneratedImageItem] = []
    poster_stage_started = time.perf_counter()
    for idx in range(payload.num_images):
        source_for_poster = generated_paths[idx] if generation_mode == "two_stage" else prepared_source_path
        if generation_mode == "two_stage":
            generated_items.append(
                GeneratedImageItem(
                    index=idx,
                    image_path=str(source_for_poster.as_posix()),
                    download_url=f"{public_prefix}/{request_id}/{source_for_poster.name}",
                )
            )

        poster_path = request_output_dir / f"poster_{idx + 1}.png"
        resolved_layout = _resolve_layout_type(payload.layout_type, idx)
        poster_prompt = _build_poster_prompt(
            payload=ImageAdRequest(**{**payload.model_dump(), "mood": applied_moods[idx]}),
            mood=applied_moods[idx],
            layout_type=resolved_layout,
        )
        if not prompt_used:
            prompt_used = poster_prompt
        poster_iter_dir = request_output_dir / f"_poster_{idx + 1}"
        poster_paths = _generate_poster_with_retries(
            provider=provider,
            source_image_path=source_for_poster,
            output_dir=poster_iter_dir,
            base_prompt=poster_prompt,
            mask_image_path=mask_path if generation_mode == "direct_poster" else None,
        )
        if not poster_paths:
            raise RuntimeError("포스터 생성 결과가 비어 있습니다.")
        shutil.move(str(poster_paths[0]), str(poster_path))
        poster_items.append(
            GeneratedImageItem(
                index=idx,
                image_path=str(poster_path.as_posix()),
                download_url=f"{public_prefix}/{request_id}/{poster_path.name}",
            )
        )
    stage_latencies_ms["poster_generation_ms"] = int((time.perf_counter() - poster_stage_started) * 1000)

    latency_ms = int((time.perf_counter() - started) * 1000)
    stage_latencies_ms["total_ms"] = latency_ms
    return ImageAdResponse(
        request_id=request_id,
        mood=payload.mood,
        prompt_used=prompt_used,
        num_images=payload.num_images,
        latency_ms=latency_ms,
        generation_mode=generation_mode,
        stage_latencies_ms=stage_latencies_ms,
        images=poster_items,
        background_images=[],
        composite_images=generated_items,
        poster_images=poster_items,
        applied_moods=applied_moods,
        seed=seed or payload.seed,
    )
