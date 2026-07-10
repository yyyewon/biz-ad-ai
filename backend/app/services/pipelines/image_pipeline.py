from __future__ import annotations

import asyncio
import time
import uuid
from typing import Optional

from loguru import logger
from PIL import Image

from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.schemas.image_ad import GenerationMode, ImageAdRequest, ImageAdResponse
from app.services.providers.factory import get_image_provider
from app.utils.image_bytes import (
    encode_image_bytes_to_base64,
    image_bytes_to_pil,
    pil_image_to_png_bytes,
)


NON_RETRYABLE_ERROR_CODES: set[str] = {
    "HF_IMAGE_PIPELINE_DEPENDENCY_ERROR",
    "HF_IMAGE_MODEL_LOAD_FAILED",
    "HF_TOKEN_MISSING",
    "MODEL_SETTINGS_NOT_FOUND",
    "OPENAI_API_KEY_MISSING",
    "PROVIDER_NOT_SUPPORTED",
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
    "가독성이 낮은 배경 위에 텍스트를 두지 말고, 텍스트 영역은 대비를 충분히 확보해줘.",
    "잘린 텍스트, 깨진 글자, 오탈자, 반복 글자, 의미 없는 문자는 절대 넣지 마.",
    "로고, 워터마크, 브랜드명, 서명, 불필요한 장식 문구를 넣지 마.",
]

POSTER_RETRY_SUFFIXES: list[str] = [
    "",
    "재시도 지시: 텍스트 정확도와 가독성을 최우선으로 다시 생성해줘. 레이아웃은 단순하고 안정적으로 구성해줘.",
    "최종 재시도 지시: 텍스트 3개를 상단/중앙에 명확히 분리 배치하고, 음식은 하단 히어로 컷으로 크게 배치해줘.",
]

async def _gather_fail_fast(coros: list) -> list:
    tasks = [asyncio.ensure_future(coro) for coro in coros]

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)

    if pending:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    for task in done:
        exc = task.exception()
        if exc is not None:
            raise exc

    return [task.result() for task in tasks]


def _build_inpaint_prompt(payload: ImageAdRequest) -> str:

    food_context = getattr(payload, "food", "") or payload.menu_name or "음식"

    prompt_chunks = [
        f"투명한 배경 영역만 자연스럽게 채워서 광고용 이미지를 만들어줘.",
        f"음식 종류는 {food_context} 야"
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

    if payload.image_request:
        prompt_chunks.append(f"추가 요청사항: {payload.image_request}")


    return ", ".join(prompt_chunks)


def _build_inpaint_mask_bytes(source_rgba: Image.Image) -> bytes:
    """
    이미지 편집용 RGBA 마스크를 PNG bytes로 생성한다.

    - 주제 영역: 불투명 알파
    - 배경 영역: 투명 알파

    서버 디스크에 mask 파일을 저장하지 않는다.
    """

    alpha = source_rgba.split()[-1]
    mask = Image.new("RGBA", source_rgba.size, (0, 0, 0, 255))
    mask.putalpha(alpha)
    return pil_image_to_png_bytes(mask)


def _resolve_layout_type(layout_type: Optional[str], index: int) -> str:
    if layout_type:
        normalized = LAYOUT_ALIAS_MAP.get(
            layout_type.strip(),
            LAYOUT_ALIAS_MAP.get(layout_type.replace(" ", "")),
        )

        if normalized and normalized != "auto":
            return normalized

    ordered = ["classic", "focus", "left"]
    return ordered[index % len(ordered)]




def _resolve_generation_mode(mode: GenerationMode | str | None) -> GenerationMode:
    if mode == "two_stage":
        return "two_stage"

    return "direct_poster"


def _build_poster_prompt(payload: ImageAdRequest, layout_type: str) -> str:
    food = (payload.food or "국")
    headline = (payload.headline or "").strip()
    menu_name = payload.menu_name or "오늘의 메뉴"
    price_text = (payload.price_text or "").strip()

    prompt_chunks = [
        "입력된 음식 사진을 기반으로 인스타그램용 세로 광고 포스터를 실사 스타일로 만들어줘.",
        f"음식 종류: {food}"
        "음식과 접시의 형태/재질은 유지하고 배경, 조명, 구도는 포스터 디자인에 맞게 새롭게 구성해줘.",
        "세련된 브랜드 광고 느낌으로 전체 레이아웃을 새로 디자인해줘. 기존 템플릿처럼 보이지 않게 다양성을 확보해줘.",
        "텍스트를 포스터 안에 직접 넣어줘. 글자 오탈자 없이 정확히 표기해줘.",
    ]

    if headline:
        prompt_chunks.append(f"표기 텍스트1(상단 카피): {headline}")
    else:
        prompt_chunks.append("표기 텍스트1(상단 카피)은 가게/목적 맥락에 맞게 자연스럽게 작성해줘.")

    prompt_chunks.extend(
        [
            f"표기 텍스트2(메뉴명, 가장 크게): {menu_name}",
            *POSTER_PROMPT_HARD_CONSTRAINTS,
            "텍스트는 가독성이 높아야 하고 음식을 과도하게 가리지 않게 배치해줘.",
            "로고/워터마크/불필요한 영문 문구는 넣지 마.",
        ]
    )

    if price_text:
        prompt_chunks.append(f"표기 텍스트3(가격): {price_text}")
        prompt_chunks.append("위에 지정한 텍스트는 띄어쓰기/문장부호/숫자/통화기호까지 정확히 동일하게 표기해줘.")
    else:
        prompt_chunks.append("가격 문구는 반드시 생략해줘.")

    if payload.promotion_goal:
        prompt_chunks.append(f"홍보 목적 맥락: {payload.promotion_goal}")

    if payload.tone:
        prompt_chunks.append(f"전반적인 문체/분위기: {payload.tone}")

    if payload.image_request:
        prompt_chunks.append(f"추가 요청사항: {payload.image_request}")


    return ", ".join(prompt_chunks)


async def _generate_poster_with_retries(
    *,
    provider,
    source_image_bytes: bytes,
    base_prompt: str,
    mask_image_bytes: bytes | None = None,
) -> list[bytes]:
    last_error: Exception | None = None

    for attempt_idx, suffix in enumerate(POSTER_RETRY_SUFFIXES):
        retry_prompt = f"{base_prompt}, {suffix}" if suffix else base_prompt

        try:
            image_bytes_list = await provider.generate(
                input_image_bytes=source_image_bytes,
                mask_image_bytes=mask_image_bytes,
                prompt=retry_prompt,
                num_images=1,
            )

            if image_bytes_list:
                return image_bytes_list

        except AppException as exc:
            if exc.code in NON_RETRYABLE_ERROR_CODES:
                logger.error(
                    "poster_generation_non_retryable_failure | code={} | error={}",
                    exc.code,
                    str(exc),
                )
                raise

            last_error = exc
            logger.warning(
                "poster_generation_attempt_failed | attempt={} | error={}",
                attempt_idx + 1,
                str(exc),
            )

        except Exception as exc:
            last_error = exc
            logger.warning(
                "poster_generation_attempt_failed | attempt={} | error={}",
                attempt_idx + 1,
                str(exc),
            )

    raise AppException(
        errors.IMAGE_POSTER_RETRY_FAILED,
        detail={
            "attempt_count": len(POSTER_RETRY_SUFFIXES),
            "last_error": str(last_error) if last_error else None,
        },
    )


async def generate_image_ads(
    payload: ImageAdRequest,
    source_image_bytes: bytes,
    seed: Optional[int] = None,
) -> ImageAdResponse:
    """
    이미지 광고 생성 파이프라인.

    메모리 기반 처리 기준:
    - 입력 이미지는 bytes로 받는다.
    - 전처리 source/mask/poster 이미지를 서버 디스크에 저장하지 않는다.
    - provider는 list[bytes]를 반환한다.
    - API 응답용 이미지는 base64 문자열로 변환한다.
    - 포스터 생성은 num_images 개수만큼 asyncio.gather로 병렬 실행한다.
    """

    started = time.perf_counter()
    request_id = f"img-{uuid.uuid4().hex[:10]}"

    if not source_image_bytes:
        raise AppException(
            errors.EMPTY_IMAGE_FILE,
            detail={"request_id": request_id},
        )

    logger.info(
        "image_pipeline_started | request_id={} | mode={} | num_images={} | input_bytes={}",
        request_id,
        payload.generation_mode,
        payload.num_images,
        len(source_image_bytes),
    )

    try:
        source_rgba = image_bytes_to_pil(source_image_bytes).convert("RGBA")
        prepared_source_bytes = pil_image_to_png_bytes(source_rgba)
        mask_bytes = _build_inpaint_mask_bytes(source_rgba)

        provider = get_image_provider()
        generation_mode = _resolve_generation_mode(payload.generation_mode)

        prompt_used = ""
        generated_image_bytes: list[bytes] = []
        generated_image_base64: list[str] = []
        stage_latencies_ms: dict[str, int] = {}

        food_stage_started = time.perf_counter()

        if generation_mode == "two_stage":
            async def _generate_food_image(idx: int) -> tuple[int, str, bytes]:
                current_prompt = _build_inpaint_prompt(payload)

                iter_images = await provider.generate(
                    input_image_bytes=prepared_source_bytes,
                    mask_image_bytes=mask_bytes,
                    prompt=current_prompt,
                    num_images=1,
                )
                
                if not iter_images:
                    raise AppException(
                        errors.IMAGE_GENERATION_EMPTY_RESULT,
                        detail={
                            "request_id": request_id,
                            "stage": "food_generation",
                            "index": idx,
                        },
                    )

                return idx, iter_images[0]

            food_results = await _gather_fail_fast(
                [_generate_food_image(idx) for idx in range(payload.num_images)]
            )

            for idx, image_bytes in sorted(food_results, key=lambda item: item[0]):
                generated_image_bytes.append(image_bytes)
                generated_image_base64.append(encode_image_bytes_to_base64(image_bytes))

                if not prompt_used:
                    prompt_used = _build_inpaint_prompt(payload)


        stage_latencies_ms["food_generation_ms"] = int(
            (time.perf_counter() - food_stage_started) * 1000
        )

        poster_stage_started = time.perf_counter()

        async def _generate_poster_image(idx: int) -> tuple[int, bytes, str]:
            source_for_poster = (
                generated_image_bytes[idx]
                if generation_mode == "two_stage"
                else prepared_source_bytes
            )

            resolved_layout = _resolve_layout_type(payload.layout_type, idx)

            poster_payload = ImageAdRequest(
                **{
                    **payload.model_dump(),
                }
            )

            poster_prompt = _build_poster_prompt(
                payload=poster_payload,
                layout_type=resolved_layout,
            )

            poster_outputs = await _generate_poster_with_retries(
                provider=provider,
                source_image_bytes=source_for_poster,
                base_prompt=poster_prompt,
                mask_image_bytes=mask_bytes if generation_mode == "direct_poster" else None,
            )

            if not poster_outputs:
                raise AppException(
                    errors.IMAGE_GENERATION_EMPTY_RESULT,
                    detail={
                        "request_id": request_id,
                        "stage": "poster_generation",
                        "index": idx,
                    },
                )

            return idx, poster_outputs[0], poster_prompt

        poster_results = await _gather_fail_fast(
            [_generate_poster_image(idx) for idx in range(payload.num_images)]
        )

        poster_image_bytes: list[bytes] = []
        for idx, poster_bytes, poster_prompt in sorted(poster_results, key=lambda item: item[0]):
            poster_image_bytes.append(poster_bytes)

            if not prompt_used:
                prompt_used = poster_prompt

        stage_latencies_ms["poster_generation_ms"] = int(
            (time.perf_counter() - poster_stage_started) * 1000
        )

        latency_ms = int((time.perf_counter() - started) * 1000)
        stage_latencies_ms["total_ms"] = latency_ms

        poster_images_base64 = [
            encode_image_bytes_to_base64(image_bytes)
            for image_bytes in poster_image_bytes
        ]

        logger.info(
            "image_pipeline_completed | request_id={} | latency_ms={} | poster_count={}",
            request_id,
            latency_ms,
            len(poster_images_base64),
        )

        return ImageAdResponse(
            request_id=request_id,
            prompt_used=prompt_used,
            num_images=payload.num_images,
            latency_ms=latency_ms,
            generation_mode=generation_mode,
            stage_latencies_ms=stage_latencies_ms,
            images=poster_images_base64,
            background_images=[],
            composite_images=generated_image_base64,
            poster_images=poster_images_base64,
            image_bytes_list=poster_image_bytes,
            seed=seed or payload.seed,
        )

    except AppException:
        raise

    except Exception as exc:
        logger.exception(
            "image_pipeline_failed | request_id={} | error={}",
            request_id,
            str(exc),
        )
        raise AppException(
            errors.IMAGE_PIPELINE_FAILED,
            detail={
                "request_id": request_id,
                "error": str(exc),
            },
        ) from exc
