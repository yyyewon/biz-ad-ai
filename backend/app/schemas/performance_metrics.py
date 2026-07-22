"""
JSONL 성능·품질 지표 매핑표.

지표 이름 → event / stage / log 파일 / extra 필드를 한곳에서 관리한다.
대시보드 GROUP BY와 백엔드 record_* 호출이 같은 stage enum을 쓰도록 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

MetricCategory = Literal[
    "integrated_api",
    "image_generation",
    "poster_vlm",
    "provider",
]
MetricStatus = Literal["implemented", "pending", "log_only", "offline_eval"]
LogTarget = Literal["performance", "quality"]


class PerformanceEvent(StrEnum):
    PERF_METRIC = "perf_metric"
    VLM_METRIC = "vlm_metric"
    QUALITY_METRIC = "quality_metric"


class PerformancePipeline(StrEnum):
    AD_GENERATE = "ad_generate"
    HF_SDXL_LIGHTNING = "hf_sdxl_lightning"


class PerformanceStage(StrEnum):
    # integrated API
    TOTAL_PIPELINE = "total_pipeline"
    TEXT_GENERATION = "text_generation"

    # image pipeline (aggregate)
    IMAGE_PIPELINE_TOTAL = "image_pipeline_total"
    POSTER_GENERATION = "poster_generation"
    FOOD_GENERATION = "food_generation"

    # image pipeline (per-variant / retry) — pending instrumentation
    VARIANT_GENERATION = "variant_generation"
    EMPTY_RESULT_RETRY = "empty_result_retry"

    # offline quality eval
    CLIP_I = "clip_i"
    CLIP_T = "clip_t"

    # poster VLM
    VLM_INFERENCE = "vlm_inference"
    VLM_JSON_PARSE = "vlm_json_parse"
    VLM_PALETTE_RECONCILE = "vlm_palette_reconcile"

    # HF provider
    MODEL_LOAD = "model_load"
    INFERENCE = "inference"


class MetricId(StrEnum):
    TOTAL_PIPELINE_LATENCY = "total_pipeline_latency"
    PIPELINE_SUCCESS_RATE = "pipeline_success_rate"
    PARTIAL_SUCCESS_RATE = "partial_success_rate"

    IMAGE_GENERATION_LATENCY = "image_generation_latency"
    VARIANT_GENERATION_LATENCY = "variant_generation_latency"
    EMPTY_RESULT_RETRY_ATTEMPT = "empty_result_retry_attempt"
    CLIP_I_SIMILARITY = "clip_i_similarity"
    CLIP_T_ALIGNMENT = "clip_t_alignment"

    VLM_JSON_PARSE_SUCCESS_RATE = "vlm_json_parse_success_rate"
    VLM_PALETTE_FALLBACK_RATE = "vlm_palette_fallback_rate"
    VLM_INFERENCE_LATENCY = "vlm_inference_latency"

    HF_MODEL_LOAD_LATENCY = "hf_model_load_latency"
    HF_INFERENCE_LATENCY = "hf_inference_latency"


LOG_TARGETS: dict[LogTarget, str] = {
    "performance": "logs/performance.jsonl",
    "quality": "logs/quality.jsonl",
}


@dataclass(frozen=True)
class MetricDefinition:
    """
    지표 한 행 = JSONL 한 줄(또는 집계 쿼리)의 contract.
    """

    metric_id: MetricId
    display_name: str
    description: str
    rationale: str
    category: MetricCategory
    status: MetricStatus
    event: PerformanceEvent
    stage: PerformanceStage
    pipeline: PerformancePipeline
    log_target: LogTarget
    extra_fields: tuple[str, ...] = field(default_factory=tuple)
    dashboard_query: str = ""
    notes: str = ""


METRIC_REGISTRY: dict[MetricId, MetricDefinition] = {
    MetricId.TOTAL_PIPELINE_LATENCY: MetricDefinition(
        metric_id=MetricId.TOTAL_PIPELINE_LATENCY,
        display_name="Total Pipeline Latency",
        description="API 1회(문구+이미지) 전체 ms",
        rationale="사용자 체감 대기 시간",
        category="integrated_api",
        status="implemented",
        event=PerformanceEvent.PERF_METRIC,
        stage=PerformanceStage.TOTAL_PIPELINE,
        pipeline=PerformancePipeline.AD_GENERATE,
        log_target="performance",
        extra_fields=("partial_success", "has_image"),
        dashboard_query="stage=total_pipeline → elapsed_ms P50/P95",
    ),
    MetricId.PIPELINE_SUCCESS_RATE: MetricDefinition(
        metric_id=MetricId.PIPELINE_SUCCESS_RATE,
        display_name="Pipeline Success Rate",
        description="완전 성공 비율",
        rationale="서비스 안정성",
        category="integrated_api",
        status="implemented",
        event=PerformanceEvent.PERF_METRIC,
        stage=PerformanceStage.TOTAL_PIPELINE,
        pipeline=PerformancePipeline.AD_GENERATE,
        log_target="performance",
        extra_fields=("partial_success",),
        dashboard_query="stage=total_pipeline → success=true 비율",
        notes="별도 stage 없음. total_pipeline.success로 집계.",
    ),
    MetricId.PARTIAL_SUCCESS_RATE: MetricDefinition(
        metric_id=MetricId.PARTIAL_SUCCESS_RATE,
        display_name="Partial Success Rate",
        description="문구만 성공 등 부분 성공",
        rationale="돌아가는데 이미지 없음",
        category="integrated_api",
        status="implemented",
        event=PerformanceEvent.PERF_METRIC,
        stage=PerformanceStage.TOTAL_PIPELINE,
        pipeline=PerformancePipeline.AD_GENERATE,
        log_target="performance",
        extra_fields=("partial_success",),
        dashboard_query="stage=total_pipeline → extra.partial_success=true 비율",
    ),
    MetricId.IMAGE_GENERATION_LATENCY: MetricDefinition(
        metric_id=MetricId.IMAGE_GENERATION_LATENCY,
        display_name="Image Generation Latency",
        description="이미지 3장+PIL까지 ms",
        rationale="OpenAI/HF·VM 속도",
        category="image_generation",
        status="implemented",
        event=PerformanceEvent.PERF_METRIC,
        stage=PerformanceStage.IMAGE_PIPELINE_TOTAL,
        pipeline=PerformancePipeline.AD_GENERATE,
        log_target="performance",
        extra_fields=("image_request_id", "num_images", "applied_variants"),
        dashboard_query="stage=image_pipeline_total → elapsed_ms",
        notes="poster_generation은 variant 배치 합산. variant별은 variant_generation.",
    ),
    MetricId.VARIANT_GENERATION_LATENCY: MetricDefinition(
        metric_id=MetricId.VARIANT_GENERATION_LATENCY,
        display_name="Variant Generation Latency",
        description="studio / poster / instagram_feed 각각 ms",
        rationale="variant별 병목",
        category="image_generation",
        status="implemented",
        event=PerformanceEvent.PERF_METRIC,
        stage=PerformanceStage.VARIANT_GENERATION,
        pipeline=PerformancePipeline.AD_GENERATE,
        log_target="performance",
        extra_fields=("variant", "render_mode", "provider"),
        dashboard_query="stage=variant_generation → GROUP BY extra.variant",
    ),
    MetricId.EMPTY_RESULT_RETRY_ATTEMPT: MetricDefinition(
        metric_id=MetricId.EMPTY_RESULT_RETRY_ATTEMPT,
        display_name="Empty-Result Retry Attempt",
        description="1·2·3차 중 몇 번에 성공",
        rationale="프롬프트·모델 품질",
        category="image_generation",
        status="implemented",
        event=PerformanceEvent.PERF_METRIC,
        stage=PerformanceStage.EMPTY_RESULT_RETRY,
        pipeline=PerformancePipeline.AD_GENERATE,
        log_target="performance",
        extra_fields=("variant", "attempt", "attempt_max", "render_mode", "success"),
        dashboard_query="stage=empty_result_retry → GROUP BY extra.attempt",
        notes="현재 poster_generation_empty_result app log만 존재.",
    ),
    MetricId.CLIP_I_SIMILARITY: MetricDefinition(
        metric_id=MetricId.CLIP_I_SIMILARITY,
        display_name="CLIP-I (Image–Image Similarity)",
        description="업로드 vs 생성 CLIP cosine",
        rationale="원본 음식 vs 생성본 유사도",
        category="image_generation",
        status="implemented",
        event=PerformanceEvent.QUALITY_METRIC,
        stage=PerformanceStage.CLIP_I,
        pipeline=PerformancePipeline.AD_GENERATE,
        log_target="quality",
        extra_fields=("variant", "score", "eval_run_id", "upload_hash"),
        dashboard_query="stage=clip_i → extra.score 분포",
    ),
    MetricId.CLIP_T_ALIGNMENT: MetricDefinition(
        metric_id=MetricId.CLIP_T_ALIGNMENT,
        display_name="CLIP-T (Image–Text Alignment)",
        description="variant 프롬프트 vs 생성 CLIP cosine",
        rationale="no text, lower half hero 등 지시 준수",
        category="image_generation",
        status="implemented",
        event=PerformanceEvent.QUALITY_METRIC,
        stage=PerformanceStage.CLIP_T,
        pipeline=PerformancePipeline.AD_GENERATE,
        log_target="quality",
        extra_fields=("variant", "score", "eval_run_id", "prompt_hash"),
        dashboard_query="stage=clip_t → extra.score 분포",
    ),
    MetricId.VLM_JSON_PARSE_SUCCESS_RATE: MetricDefinition(
        metric_id=MetricId.VLM_JSON_PARSE_SUCCESS_RATE,
        display_name="VLM JSON Parse Success Rate",
        description="VLM JSON 적용 성공 비율",
        rationale="VLM 출력 쓸 만한지",
        category="poster_vlm",
        status="implemented",
        event=PerformanceEvent.VLM_METRIC,
        stage=PerformanceStage.VLM_JSON_PARSE,
        pipeline=PerformancePipeline.AD_GENERATE,
        log_target="performance",
        extra_fields=("model", "raw_chars"),
        dashboard_query="stage=vlm_json_parse → success 비율",
        notes="현재 poster_vlm_parse_failed / poster_vlm_applied app log.",
    ),
    MetricId.VLM_PALETTE_FALLBACK_RATE: MetricDefinition(
        metric_id=MetricId.VLM_PALETTE_FALLBACK_RATE,
        display_name="Rules Palette Fallback Rate",
        description="VLM 색 → 규칙 palette 보정 비율",
        rationale="VLM 색 힌트 신뢰도",
        category="poster_vlm",
        status="implemented",
        event=PerformanceEvent.VLM_METRIC,
        stage=PerformanceStage.VLM_PALETTE_RECONCILE,
        pipeline=PerformancePipeline.AD_GENERATE,
        log_target="performance",
        extra_fields=("used_rules_fallback",),
        dashboard_query="stage=vlm_palette_reconcile → extra.used_rules_fallback=true 비율",
        notes="현재 poster_vlm_palette_reconciled app log.",
    ),
    MetricId.VLM_INFERENCE_LATENCY: MetricDefinition(
        metric_id=MetricId.VLM_INFERENCE_LATENCY,
        display_name="VLM Inference Latency",
        description="VLM 1회 추론 ms",
        rationale="GPU 비용·CPU hang",
        category="poster_vlm",
        status="implemented",
        event=PerformanceEvent.VLM_METRIC,
        stage=PerformanceStage.VLM_INFERENCE,
        pipeline=PerformancePipeline.AD_GENERATE,
        log_target="performance",
        extra_fields=("model",),
        dashboard_query="stage=vlm_inference → elapsed_ms",
    ),
    MetricId.HF_MODEL_LOAD_LATENCY: MetricDefinition(
        metric_id=MetricId.HF_MODEL_LOAD_LATENCY,
        display_name="HF Model Load Latency",
        description="SDXL Lightning 가중치 로드 ms",
        rationale="콜드스타트·VM 메모리",
        category="provider",
        status="implemented",
        event=PerformanceEvent.PERF_METRIC,
        stage=PerformanceStage.MODEL_LOAD,
        pipeline=PerformancePipeline.HF_SDXL_LIGHTNING,
        log_target="performance",
        extra_fields=("device", "dtype", "xformers_enabled"),
        dashboard_query="pipeline=hf_sdxl_lightning, stage=model_load",
    ),
    MetricId.HF_INFERENCE_LATENCY: MetricDefinition(
        metric_id=MetricId.HF_INFERENCE_LATENCY,
        display_name="HF Inference Latency",
        description="SDXL Lightning 1회 inference ms",
        rationale="이미지 생성 GPU 병목",
        category="provider",
        status="implemented",
        event=PerformanceEvent.PERF_METRIC,
        stage=PerformanceStage.INFERENCE,
        pipeline=PerformancePipeline.HF_SDXL_LIGHTNING,
        log_target="performance",
        extra_fields=("render_mode", "num_images"),
        dashboard_query="pipeline=hf_sdxl_lightning, stage=inference",
    ),
}


def get_metric_definition(metric_id: MetricId | str) -> MetricDefinition:
    if isinstance(metric_id, MetricId):
        key = metric_id
    else:
        try:
            key = MetricId(metric_id)
        except ValueError as exc:
            raise KeyError(f"unknown metric_id: {metric_id}") from exc

    try:
        return METRIC_REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"unknown metric_id: {key}") from exc


def list_metrics(
    *,
    category: MetricCategory | None = None,
    status: MetricStatus | None = None,
) -> list[MetricDefinition]:
    items = list(METRIC_REGISTRY.values())

    if category is not None:
        items = [item for item in items if item.category == category]

    if status is not None:
        items = [item for item in items if item.status == status]

    return items


def resolve_log_relative_path(log_target: LogTarget) -> str:
    return LOG_TARGETS[log_target]


def build_metric_record(
    metric_id: MetricId | str,
    *,
    timestamp: str,
    request_id: str,
    elapsed_ms: float | None = None,
    success: bool,
    provider: str = "mixed",
    model: str = "mixed",
    profile: str | None = None,
    error_code: str | None = None,
    error_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    매핑표 정의 + 런타임 값 → JSONL 1줄 dict.

    elapsed_ms가 None이면 success/rate 전용 레코드(집계형 지표)로 기록한다.
    """

    definition = get_metric_definition(metric_id)
    record: dict[str, Any] = {
        "event": definition.event.value,
        "metric_id": definition.metric_id.value,
        "timestamp": timestamp,
        "request_id": request_id,
        "pipeline": definition.pipeline.value,
        "profile": profile or "unknown",
        "stage": definition.stage.value,
        "provider": provider,
        "model": model,
        "success": success,
    }

    if elapsed_ms is not None:
        record["elapsed_ms"] = round(float(elapsed_ms), 3)

    if error_code:
        record["error_code"] = error_code

    if error_type:
        record["error_type"] = error_type

    if extra:
        record["extra"] = extra

    return record


def metric_mapping_table_rows() -> list[dict[str, str]]:
    """
    Streamlit 대시보드·문서용 flat 행 목록.
    """

    rows: list[dict[str, str]] = []

    for definition in METRIC_REGISTRY.values():
        rows.append(
            {
                "metric_id": definition.metric_id.value,
                "display_name": definition.display_name,
                "category": definition.category,
                "status": definition.status,
                "event": definition.event.value,
                "stage": definition.stage.value,
                "pipeline": definition.pipeline.value,
                "log_file": LOG_TARGETS[definition.log_target],
                "extra_fields": ", ".join(definition.extra_fields),
                "dashboard_query": definition.dashboard_query,
            }
        )

    return rows
