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
        title="통합 API · 서비스 운영",
        subtitle="광고 생성 API 1회 호출 전체 (문구 + 이미지)",
        purpose="사용자가 생성 버튼 눌렀을 때 서비스가 제대로 끝까지 도는지",
        data_source="`performance.jsonl` (`stage=total_pipeline`)",
    ),
    DashboardSection(
        key="image_generation",
        title="이미지 생성",
        subtitle="OpenAI/HF edit · variant 3장 (studio / poster / feed) · PIL 합성",
        purpose="이미지 생성·후처리 속도, 원본 유지·프롬프트 준수",
        data_source="속도: `performance.jsonl` · 품질: `quality.jsonl`",
    ),
    DashboardSection(
        key="poster_vlm",
        title="포스터 VLM",
        subtitle="Qwen2-VL — palette · scrim · typography JSON (`poster_layout`)",
        purpose="VLM 출력 품질·latency",
        data_source="`performance.jsonl` (VLM stages) · app log",
    ),
)

METRIC_CATALOG: dict[MetricCategory, tuple[MetricCatalogItem, ...]] = {
    "integrated_api": (
        MetricCatalogItem(
            "Total Pipeline Latency",
            "total_pipeline",
            "API 1회(문구+이미지) 전체 소요",
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
            "Image Generation Latency",
            "image_pipeline_total",
            "이미지 3장+PIL까지",
            "OpenAI/HF·VM 속도",
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
            "지시 준수 (no text 등)",
            "✅",
            log_target="quality.jsonl",
        ),
    ),
    "poster_vlm": (
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
        MetricCatalogItem(
            "VLM Inference Latency",
            "vlm_inference",
            "VLM 1회 추론",
            "GPU 비용·hang",
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
**Latency:** `P50` / `P95` = `elapsed_ms` 백분위 (차트는 **초**).

**Stage / metric:** 영문 이름 = JSONL `stage` 키.

**필터:** `source_user`, `deploy_env`, port = `extra.*`.
"""

VARIANT_CHART_HELP = (
    metric_help_by_name("Variant Generation Latency")
    + "\n\n차트 Y값: **초** (`elapsed_ms` ÷ 1000)."
)
RETRY_CHART_HELP = metric_help_by_name("Empty-Result Retry Attempt")
CLIP_I_CHART_HELP = metric_help_by_name("CLIP-I (Image–Image Similarity)") + "\n\n점수 **0~1**."
CLIP_T_CHART_HELP = metric_help_by_name("CLIP-T (Image–Text Alignment)") + "\n\n점수 **0~1**."

METRIC_HELP = {
    "Total Pipeline Latency (P50)": metric_help_by_name("Total Pipeline Latency"),
    "Total Pipeline Latency (P95)": metric_help_by_name("Total Pipeline Latency"),
    "Pipeline Success Rate": metric_help_by_name("Pipeline Success Rate"),
    "Partial Success Rate": metric_help_by_name("Partial Success Rate"),
    "Image Generation Latency (P50)": metric_help_by_name("Image Generation Latency"),
    "VLM Inference Latency (P50)": metric_help_by_name("VLM Inference Latency"),
    "VLM JSON Parse Success Rate": metric_help_by_name("VLM JSON Parse Success Rate"),
    "Rules Palette Fallback Rate": metric_help_by_name("Rules Palette Fallback Rate"),
}

SECTION_HELP: dict[str, str] = {
    s.title: f"{s.subtitle}\n\n{s.purpose}\n\n**데이터:** {s.data_source}"
    for s in SECTIONS
}

SECTION_HELP["팀별 생성 수"] = (
    "필터 무관 · `total_pipeline` run을 `extra.source_user`별 집계."
)

STAGE_HELP: dict[str, str] = {
    item.stage: item.description
    for items in METRIC_CATALOG.values()
    for item in items
}
