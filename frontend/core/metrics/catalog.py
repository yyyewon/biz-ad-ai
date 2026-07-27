"""
Metrics dashboard — 섹션·지표 catalog (? 설명용).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MetricCategory = Literal["integrated_api", "image_generation", "poster_vlm"]


@dataclass(frozen=True)
class MetricCatalogItem:
    display_name: str
    stage: str
    description: str
    rationale: str
    status: str
    log_target: str = "performance.jsonl"


@dataclass(frozen=True)
class DashboardSection:
    key: MetricCategory
    title: str
    subtitle: str
    purpose: str
    data_source: str


SECTIONS: tuple[DashboardSection, ...] = (
    DashboardSection(
        key="integrated_api",
        title="통합 파이프라인",
        subtitle="광고 생성 API 1회 호출 전체 wall clock",
        purpose="사용자가 생성 버튼 눌렀을 때 끝까지 걸린 전체 서비스 시간",
        data_source="`performance.jsonl` · `stage=total_pipeline`",
    ),
    DashboardSection(
        key="image_generation",
        title="이미지 생성",
        subtitle="provider · variant · overlay · image track",
        purpose="이미지 트랙 breakdown, variant/품질 지표",
        data_source="속도: `performance.jsonl` · 품질: `quality.jsonl`",
    ),
    DashboardSection(
        key="poster_vlm",
        title="포스터 VLM",
        subtitle="Qwen2-VL — palette · scrim · typography JSON",
        purpose="VLM 출력 품질·latency",
        data_source="`performance.jsonl` (VLM stages)",
    ),
)

METRIC_CATALOG: dict[MetricCategory, tuple[MetricCatalogItem, ...]] = {
    "integrated_api": (
        MetricCatalogItem(
            "Total Pipeline Latency",
            "total_pipeline",
            "API 1회 전체 (문구+이미지 **병렬**)",
            "사용자 체감 대기 시간",
            "✅",
        ),
        MetricCatalogItem(
            "Pipeline Success Rate",
            "total_pipeline",
            "완전 성공 비율",
            "서비스 안정성",
            "✅",
        ),
        MetricCatalogItem(
            "Partial Success Rate",
            "total_pipeline",
            "문구만 성공 등 부분 성공",
            "돌아가는데 이미지 없음",
            "✅",
        ),
    ),
    "image_generation": (
        MetricCatalogItem(
            "Image Generation (3 variants)",
            "poster_generation",
            "studio / poster / feed 3장 variant loop wall clock",
            "요약 지표 — variant 루프 실제 소요",
            "✅",
        ),
        MetricCatalogItem(
            "Image Generation (provider sum)",
            "image_provider_generation_sum",
            "OpenAI/HF provider 추론 합산 (VLM·overlay 제외)",
            "provider inference only",
            "✅",
        ),
        MetricCatalogItem(
            "Image Track Total",
            "image_pipeline_total",
            "provider + VLM + overlay wall clock",
            "이미지 트랙 전체",
            "✅",
        ),
        MetricCatalogItem(
            "Poster VLM + Overlay",
            "image_poster_vlm_overlay",
            "VLM batch + PIL 텍스트 합성",
            "provider 이후 후처리",
            "✅",
        ),
        MetricCatalogItem(
            "Variant Generation Latency",
            "variant_generation",
            "studio / poster / instagram_feed 각각",
            "variant별 병목",
            "✅",
        ),
        MetricCatalogItem(
            "Empty-Result Retry Attempt",
            "empty_result_retry",
            "1·2·3차 attempt 분포",
            "프롬프트·모델 품질",
            "✅",
        ),
        MetricCatalogItem(
            "CLIP-I (Image–Image Similarity)",
            "clip_i",
            "업로드 vs 생성 cosine",
            "원본 음식 보존",
            "✅",
            log_target="quality.jsonl",
        ),
        MetricCatalogItem(
            "CLIP-T (Image–Text Alignment)",
            "clip_t",
            "프롬프트 vs 생성 cosine",
            "지시 준수",
            "✅",
            log_target="quality.jsonl",
        ),
    ),
    "poster_vlm": (
        MetricCatalogItem(
            "VLM Inference Latency",
            "vlm_inference",
            "VLM batch 추론 ms",
            "요약 지표 — layout JSON 생성",
            "✅",
        ),
        MetricCatalogItem(
            "VLM JSON Parse Success Rate",
            "vlm_json_parse",
            "VLM JSON 적용 성공 비율",
            "VLM 출력 쓸 만한지",
            "✅",
        ),
        MetricCatalogItem(
            "Rules Palette Fallback Rate",
            "vlm_palette_reconcile",
            "규칙 palette 보정 비율",
            "VLM 색 힌트 신뢰도",
            "✅",
        ),
    ),
}


def metric_help_text(item: MetricCatalogItem) -> str:
    return (
        f"**{item.display_name}**\n\n"
        f"- stage: `{item.stage}`\n"
        f"- data: `{item.log_target}`\n\n"
        f"**설명:** {item.description}\n\n"
        f"**왜 필요한지:** {item.rationale}"
    )


def metric_help_by_name(display_name: str) -> str:
    for items in METRIC_CATALOG.values():
        for item in items:
            if item.display_name == display_name:
                return metric_help_text(item)
    return ""


GLOSSARY_MD = """
**요약 (상단):** 통합 파이프라인 · 이미지 3장 생성 · 포스터 VLM

**상세 지표:** provider breakdown · variant · CLIP · VLM 품질 등

**Latency:** 필터 전체 = P50/P95 · **요청 ID 1개** = 그 run의 실제 elapsed
"""

VARIANT_CHART_HELP = (
    metric_help_by_name("Variant Generation Latency")
    + "\n\n차트 Y값: **초** (`elapsed_ms` ÷ 1000)."
)
RETRY_CHART_HELP = metric_help_by_name("Empty-Result Retry Attempt")
CLIP_I_CHART_HELP = metric_help_by_name("CLIP-I (Image–Image Similarity)") + "\n\n점수 **0~1**."
CLIP_T_CHART_HELP = metric_help_by_name("CLIP-T (Image–Text Alignment)") + "\n\n점수 **0~1**."

METRIC_HELP = {
    "Total Pipeline Latency": metric_help_by_name("Total Pipeline Latency"),
    "Total Pipeline Latency (P50)": (
        metric_help_by_name("Total Pipeline Latency")
        + "\n\n**참고:** 문구·이미지는 **동시에** 돌아갑니다."
    ),
    "Image Generation (3 variants)": metric_help_by_name("Image Generation (3 variants)"),
    "VLM Inference Latency": metric_help_by_name("VLM Inference Latency"),
    "VLM Inference Latency (P50)": metric_help_by_name("VLM Inference Latency"),
    "Pipeline Success Rate": metric_help_by_name("Pipeline Success Rate"),
    "Partial Success Rate": metric_help_by_name("Partial Success Rate"),
    "VLM JSON Parse Success Rate": metric_help_by_name("VLM JSON Parse Success Rate"),
    "Rules Palette Fallback Rate": metric_help_by_name("Rules Palette Fallback Rate"),
}

SECTION_HELP: dict[str, str] = {
    s.title: f"{s.subtitle}\n\n{s.purpose}\n\n**데이터:** {s.data_source}"
    for s in SECTIONS
}

SECTION_HELP["성능 요약"] = (
    "통합 파이프라인 · 이미지 3장 생성 · 포스터 VLM — 핵심 3지표."
)
SECTION_HELP["팀별 생성 수"] = (
    "필터 무관 · `total_pipeline` run을 `extra.source_user`별 집계."
)
