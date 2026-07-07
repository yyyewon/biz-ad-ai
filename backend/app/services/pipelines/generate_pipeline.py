import base64
import uuid
from pathlib import Path

from loguru import logger

from app.core.config import get_settings
from app.schemas.image_ad import ImageAdRequest
from app.services.pipelines.image_pipeline import generate_image_ads
from app.services.pipelines.text_pipeline import run_text_pipeline
from app.api.v1.endpoints.image_preprocess import run_remove_background_and_resize


EXTRA_MOOD_ALIAS_MAP: dict[str, str] = {
    "우드톤 내추럴": "cozy",
    "밤분위기 무드": "luxury",
    "비비드 팝": "fresh",
}


def _normalize_image_moods(moods: list[str]) -> tuple[str, list[str] | None]:
    normalized: list[str] = []
    for mood in moods:
        normalized.append(EXTRA_MOOD_ALIAS_MAP.get(mood, mood))
    if not normalized:
        return "cozy", None
    return normalized[0], normalized


def _encode_file_to_base64(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode("utf-8")


def run_generate_pipeline(
    store_name: str, 
    menu_name: str, 
    purpose: str, 
    request_note: str, 
    moods: list, 
    tone: str,
    image_bytes: bytes = None
):
    
    """
    텍스트 파이프라인과 이미지 전처리를 총괄하는 마스터 파이프라인
    """
    # 텍스트 카피라이팅 문구 생성
    caption = run_text_pipeline(
        store_name=store_name,
        menu_name=menu_name,
        purpose=purpose,
        request_note=request_note,
        moods=moods,
        tone=tone
    )
    
    images: list[str] = []
    image_generation: dict = {}
    image_generation_error: str | None = None
    
    # 이미지 배경 제거 로직
    if image_bytes:
        processed_bytes: bytes | None = None
        try:
            # 팀원의 누끼 + 리사이징 함수 호출
            processed_bytes = run_remove_background_and_resize(image_bytes)
            
            if processed_bytes:
                settings = get_settings()
                request_id = f"gen-{uuid.uuid4().hex[:8]}"
                request_dir = settings.output_dir / "_generate" / request_id
                request_dir.mkdir(parents=True, exist_ok=True)

                source_path = request_dir / "source_rgba.png"
                source_path.write_bytes(processed_bytes)

                normalized_mood, normalized_mood_list = _normalize_image_moods(moods or [])
                image_payload = ImageAdRequest(
                    input_image_path=str(source_path.as_posix()),
                    store_name=store_name,
                    menu_name=menu_name,
                    promotion_goal=purpose,
                    tone=tone,
                    extra_notes=request_note,
                    mood=normalized_mood,
                    mood_list=normalized_mood_list,
                    num_images=3,
                    generation_mode="direct_poster",
                )
                image_result = generate_image_ads(
                    payload=image_payload,
                    output_root=settings.output_dir,
                    public_prefix="/outputs",
                )
                images = [
                    _encode_file_to_base64(item.image_path)
                    for item in image_result.poster_images
                ]
                # UI 3분할 피드 그리드를 안정적으로 채우기 위해 최소 3장을 보장합니다.
                if images:
                    while len(images) < 3:
                        images.append(images[-1])
                image_generation = {
                    "request_id": image_result.request_id,
                    "generation_mode": image_result.generation_mode,
                    "latency_ms": image_result.latency_ms,
                    "stage_latencies_ms": image_result.stage_latencies_ms,
                    "poster_images": [item.model_dump() for item in image_result.poster_images],
                }
        except Exception:
            # 생성 실패 시에도 UI가 비어 보이지 않도록 사용 가능한 입력 이미지를 3장으로 채워 전달합니다.
            logger.exception("image_generation_failed_in_generate_pipeline")
            fallback_bytes = processed_bytes or image_bytes
            fallback_b64 = base64.b64encode(fallback_bytes).decode("utf-8")
            images = [fallback_b64, fallback_b64, fallback_b64]
            image_generation_error = "포스터 생성 실패로 fallback 이미지를 반환했습니다."

    response = {
        "caption": caption,
        "images": images  # 전처리된 이미지가 담겨서 나감
    }
    if image_generation:
        response["image_generation"] = image_generation
    if image_generation_error:
        response["image_generation_error"] = image_generation_error
    return response