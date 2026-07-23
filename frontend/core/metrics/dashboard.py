"""
Metrics dashboard UI (metrics_app.py entry).
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from core.metrics.aggregations import (
    count_by_extra,
    dict_ms_to_sec,
    format_ms,
    group_mean_elapsed_ms,
    group_mean_score,
    latency_summary,
    partial_success_rate,
    success_rate,
)
from core.metrics.catalog import (
    CLIP_I_CHART_HELP,
    CLIP_T_CHART_HELP,
    GLOSSARY_MD,
    METRIC_CATALOG,
    METRIC_HELP,
    RETRY_CHART_HELP,
    SECTION_HELP,
    SECTIONS,
    VARIANT_CHART_HELP,
    MetricCatalogItem,
)
from core.metrics.config import PERFORMANCE_LOG_PATH, QUALITY_LOG_PATH
from core.metrics.jsonl_loader import (
    apply_dashboard_filters,
    filter_records,
    load_jsonl,
    unique_extra_values,
    unique_request_ids,
)

_FILTER_ALL = "(전체)"


@st.cache_data(ttl=30)
def _load_logs() -> tuple[list, list]:
    return load_jsonl(PERFORMANCE_LOG_PATH), load_jsonl(QUALITY_LOG_PATH)


def _help_popover(text: str, *, label: str = "?") -> None:
    with st.popover(label):
        st.markdown(text)


def _section_header(title: str) -> None:
    help_text = SECTION_HELP.get(title, "")
    left, right = st.columns([11, 1], vertical_alignment="center")
    with left:
        st.subheader(title)
    with right:
        if help_text:
            _help_popover(help_text)


def _chart_header(title: str, help_text: str, *, unit: str | None = None) -> None:
    left, right = st.columns([11, 1], vertical_alignment="center")
    with left:
        st.markdown(f"**{title}**")
        if unit:
            st.caption(f"단위: {unit}")
    with right:
        _help_popover(help_text)


def _vertical_bar_chart(
    series: pd.Series,
    *,
    category_col: str,
    value_col: str,
    height: int = 280,
) -> None:
    """세로 bar — x축 카테고리 가로. y축 제목은 caption (회전 방지)."""
    df = (
        series.rename_axis(category_col)
        .reset_index(name=value_col)
        .sort_values(value_col, ascending=False)
    )
    if df.empty:
        return

    bar_count = len(df)
    step = max(52, min(88, 640 // max(bar_count, 1)))

    chart = (
        alt.Chart(df)
        .mark_bar(color="#4C78A8")
        .encode(
            x=alt.X(
                f"{category_col}:N",
                sort=None,
                title=None,
                axis=alt.Axis(labelAngle=0, labelOverlap=False, labelLimit=120),
            ),
            y=alt.Y(
                f"{value_col}:Q",
                title=None,
                axis=alt.Axis(titleAngle=0, labelAngle=0),
            ),
            tooltip=[
                alt.Tooltip(category_col, title=category_col),
                alt.Tooltip(value_col, title=value_col, format=".2f"),
            ],
        )
        .properties(height=height, width=alt.Step(step))
    )
    st.altair_chart(chart, use_container_width=True)


def _render_metric_catalog_table(items: tuple[MetricCatalogItem, ...]) -> None:
    with st.expander("지표 목록 (metric catalog)"):
        rows = [
            {
                "지표": item.display_name,
                "stage": item.stage,
                "설명": item.description,
                "왜 필요한지": item.rationale,
                "상태": item.status,
            }
            for item in items
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_section_intro(section_key: str) -> None:
    section = next(s for s in SECTIONS if s.key == section_key)
    st.markdown(f"> {section.subtitle}")
    st.caption(section.purpose)
    st.caption(f"데이터: {section.data_source}")


def _render_sidebar_filters(all_records: list) -> dict[str, str | None]:
    st.sidebar.header("필터")

    if st.sidebar.button("새로고침", use_container_width=True):
        _load_logs.clear()
        st.rerun()

    with st.sidebar.expander("지표 설명"):
        st.markdown(GLOSSARY_MD)

    total_runs = filter_records(all_records, stage="total_pipeline")

    st.sidebar.subheader("운영 · 로그")
    source_user = st.sidebar.selectbox(
        "사용자 (source_user)",
        options=[_FILTER_ALL] + unique_extra_values(all_records, "source_user"),
    )
    deploy_env = st.sidebar.selectbox(
        "환경 (deploy_env)",
        options=[_FILTER_ALL] + unique_extra_values(all_records, "deploy_env"),
    )
    backend_port = st.sidebar.selectbox(
        "Backend 포트",
        options=[_FILTER_ALL] + unique_extra_values(all_records, "backend_port"),
    )
    frontend_port = st.sidebar.selectbox(
        "Frontend 포트",
        options=[_FILTER_ALL] + unique_extra_values(all_records, "frontend_port"),
    )
    selected_request = st.sidebar.selectbox(
        "요청 ID (request_id)",
        options=[_FILTER_ALL] + unique_request_ids(all_records)[::-1],
    )

    st.sidebar.divider()
    st.sidebar.subheader("생성 조건")
    st.sidebar.caption("total_pipeline에 기록된 입력값·이미지 모델로 run을 좁힙니다.")

    image_model = st.sidebar.selectbox(
        "이미지 모델 (provider/model)",
        options=[_FILTER_ALL] + unique_extra_values(total_runs, "image_model_key"),
        key="filter_image_model",
    )
    purpose = st.sidebar.selectbox(
        "홍보 목적 (purpose)",
        options=[_FILTER_ALL] + unique_extra_values(total_runs, "purpose"),
        key="filter_purpose",
    )
    food_type = st.sidebar.selectbox(
        "음식 형태 (food_type)",
        options=[_FILTER_ALL] + unique_extra_values(total_runs, "food_type"),
        key="filter_food_type",
    )
    tone = st.sidebar.selectbox(
        "톤앤매너 (tone)",
        options=[_FILTER_ALL] + unique_extra_values(total_runs, "tone"),
        key="filter_tone",
    )

    with st.sidebar.expander("로그 경로"):
        st.code(str(PERFORMANCE_LOG_PATH), language=None)
        st.code(str(QUALITY_LOG_PATH), language=None)

    def _pick(value: str) -> str | None:
        return None if value == _FILTER_ALL else value

    return {
        "request_id": _pick(selected_request),
        "source_user": _pick(source_user),
        "backend_port": _pick(backend_port),
        "frontend_port": _pick(frontend_port),
        "deploy_env": _pick(deploy_env),
        "image_model_key": _pick(image_model),
        "purpose": _pick(purpose),
        "food_type": _pick(food_type),
        "tone": _pick(tone),
    }


def _apply_filters(
    all_performance: list,
    all_quality: list,
    filters: dict[str, str | None],
) -> tuple[list, list]:
    return apply_dashboard_filters(
        all_performance,
        all_quality,
        request_id=filters.get("request_id"),
        source_user=filters.get("source_user"),
        backend_port=filters.get("backend_port"),
        frontend_port=filters.get("frontend_port"),
        deploy_env=filters.get("deploy_env"),
        purpose=filters.get("purpose"),
        tone=filters.get("tone"),
        food_type=filters.get("food_type"),
        image_model_key=filters.get("image_model_key"),
    )


_OPERATIONS_FILTER_KEYS = (
    "source_user",
    "deploy_env",
    "backend_port",
    "frontend_port",
    "request_id",
)
_GENERATION_FILTER_KEYS = (
    "image_model_key",
    "purpose",
    "food_type",
    "tone",
)


def _filter_caption(filters: dict[str, str | None], keys: tuple[str, ...]) -> str:
    labels = {
        "source_user": "사용자",
        "deploy_env": "환경",
        "backend_port": "BE",
        "frontend_port": "FE",
        "request_id": "요청",
        "image_model_key": "이미지모델",
        "purpose": "목적",
        "food_type": "음식형태",
        "tone": "톤",
    }
    parts = [f"{labels.get(k, k)}={filters[k]}" for k in keys if filters.get(k)]
    return " · ".join(parts) if parts else "전체"


def _render_team_overview(all_performance: list) -> None:
    pipeline_records = filter_records(all_performance, stage="total_pipeline")
    source_counts = count_by_extra(pipeline_records, "source_user")
    if not source_counts:
        return

    _section_header("팀별 생성 수")
    _chart_header("Runs by source_user", SECTION_HELP["팀별 생성 수"], unit="run 수")
    _vertical_bar_chart(
        pd.Series(source_counts, name="runs"),
        category_col="source_user",
        value_col="runs",
        height=220,
    )
    st.divider()


def _render_integrated_api_section(
    performance_records: list,
    total_records: list,
) -> None:
    _section_header("통합 API · 서비스 운영")
    _render_section_intro("integrated_api")
    _render_metric_catalog_table(METRIC_CATALOG["integrated_api"])

    summary = latency_summary(total_records)
    success = success_rate(total_records)
    partial = partial_success_rate(total_records)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Total Pipeline Latency (P50)",
        format_ms(summary["p50_ms"]),
        help=METRIC_HELP["Total Pipeline Latency (P50)"],
    )
    c2.metric(
        "Total Pipeline Latency (P95)",
        format_ms(summary["p95_ms"]),
        help=METRIC_HELP["Total Pipeline Latency (P95)"],
    )
    c3.metric(
        "Pipeline Success Rate",
        f"{success}%" if success is not None else "-",
        help=METRIC_HELP["Pipeline Success Rate"],
    )
    c4.metric(
        "Partial Success Rate",
        f"{partial}%" if partial is not None else "-",
        help=METRIC_HELP["Partial Success Rate"],
    )
    st.caption(f"Runs (`total_pipeline`): **{summary['count']}** · 문구-only run 포함")
    _render_run_context_comparison(total_records)


def _records_for_image_runs(
    performance_records: list,
    *,
    stage: str,
) -> list:
    """
    image_pipeline_total 이 있는 request_id만 묶어 stage별 latency를 맞춘다.
    Total vs Image 비교 시 같은 run 집합을 쓰기 위함.
    """

    image_run_ids = {
        str(record["request_id"])
        for record in filter_records(performance_records, stage="image_pipeline_total")
        if record.get("request_id")
    }
    if not image_run_ids:
        return []

    return [
        record
        for record in filter_records(performance_records, stage=stage)
        if str(record.get("request_id")) in image_run_ids
    ]


def _render_run_context_comparison(total_records: list) -> None:
    if not total_records:
        return

    dimensions = [
        ("image_model_key", "이미지 모델"),
        ("purpose", "홍보 목적"),
        ("food_type", "음식 형태"),
        ("tone", "톤앤매너"),
    ]

    with st.expander("생성 조건별 latency 비교"):
        st.caption("현재 필터 범위 안에서 그룹별 평균 total_pipeline elapsed_ms")
        for key, label in dimensions:
            grouped = group_mean_elapsed_ms(total_records, key)
            counts = count_by_extra(total_records, key)
            if not grouped:
                continue

            st.markdown(f"**{label}**")
            rows = []
            for group_name, mean_ms in sorted(grouped.items(), key=lambda item: item[1]):
                rows.append(
                    {
                        "group": group_name,
                        "runs": counts.get(group_name, 0),
                        "mean_sec": round(mean_ms / 1000, 2),
                    }
                )
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
            _vertical_bar_chart(
                pd.Series(
                    {row["group"]: row["mean_sec"] for row in rows},
                    name="mean_sec",
                ),
                category_col="group",
                value_col="mean_sec",
                height=220,
            )


def _render_image_generation_section(
    performance_records: list,
    quality_records: list,
) -> None:
    _section_header("이미지 생성")
    _render_section_intro("image_generation")
    _render_metric_catalog_table(METRIC_CATALOG["image_generation"])

    image_records = filter_records(performance_records, stage="image_pipeline_total")
    image_summary = latency_summary(image_records)

    aligned_text = latency_summary(
        _records_for_image_runs(performance_records, stage="text_generation")
    )
    aligned_total = latency_summary(
        _records_for_image_runs(performance_records, stage="total_pipeline")
    )

    c1, c2 = st.columns(2)
    c1.metric(
        "Image Pipeline Total (P50)",
        format_ms(image_summary["p50_ms"]),
        help=METRIC_HELP["Image Generation Latency (P50)"],
    )
    c2.metric(
        "Image Pipeline Total (P95)",
        format_ms(image_summary["p95_ms"]),
        help=METRIC_HELP["Image Generation Latency (P50)"],
    )
    st.caption(
        f"Runs (`image_pipeline_total`): **{image_summary['count']}** · "
        "stage=`image_pipeline_total` (이미지 3장+PIL 내부)"
    )

    if aligned_text["count"] or aligned_total["count"]:
        st.markdown("**같은 run 기준 병렬 비교** (이미지 포함 요청만)")
        st.caption(
            "문구·이미지는 동시 실행 → Total Pipeline은 max(문구, 이미지)에 가깝습니다. "
            "순차 합(문구+이미지)이 아닙니다."
        )
        t1, t2, t3 = st.columns(3)
        t1.metric(
            "Text Generation (P50)",
            format_ms(aligned_text["p50_ms"]),
            help="stage=`text_generation` · 이미지 run과 동일 request_id",
        )
        t2.metric(
            "Image Pipeline Total (P50)",
            format_ms(image_summary["p50_ms"]),
            help="stage=`image_pipeline_total`",
        )
        t3.metric(
            "Total Pipeline (P50)",
            format_ms(aligned_total["p50_ms"]),
            help="stage=`total_pipeline` · API 전체 wall clock",
        )

    variant_records = filter_records(performance_records, stage="variant_generation")
    variant_means = group_mean_elapsed_ms(variant_records, "variant")
    if variant_means:
        _chart_header(
            "Variant Generation Latency (`variant_generation`)",
            VARIANT_CHART_HELP,
            unit="초",
        )
        _vertical_bar_chart(
            pd.Series(dict_ms_to_sec(variant_means), name="sec"),
            category_col="variant",
            value_col="sec",
        )

    retry_records = filter_records(performance_records, stage="empty_result_retry")
    if retry_records:
        _chart_header(
            "Empty-Result Retry Attempt (`empty_result_retry`)",
            RETRY_CHART_HELP,
            unit="횟수",
        )
        _vertical_bar_chart(
            pd.Series(count_by_extra(retry_records, "attempt"), name="count"),
            category_col="attempt",
            value_col="count",
            height=220,
        )

    clip_i = filter_records(quality_records, stage="clip_i")
    clip_t = filter_records(quality_records, stage="clip_t")
    clip_i_means = group_mean_score(clip_i)
    clip_t_means = group_mean_score(clip_t)

    left, right = st.columns(2)
    with left:
        _chart_header("CLIP-I (`clip_i`)", CLIP_I_CHART_HELP, unit="0~1")
        if clip_i_means:
            _vertical_bar_chart(
                pd.Series(clip_i_means, name="score"),
                category_col="variant",
                value_col="score",
                height=220,
            )
        else:
            clip_count = len(clip_i) + len(clip_t)
            if quality_records:
                st.caption(
                    f"CLIP stage 없음 (quality {len(quality_records)}줄, clip {clip_count}줄). "
                    "이미지 생성 성공 후 CLIP eval이 끝나야 쌓입니다."
                )
            else:
                st.caption("quality.jsonl 데이터 없음 (필터 범위 또는 파일 경로 확인)")

    with right:
        _chart_header("CLIP-T (`clip_t`)", CLIP_T_CHART_HELP, unit="0~1")
        if clip_t_means:
            _vertical_bar_chart(
                pd.Series(clip_t_means, name="score"),
                category_col="variant",
                value_col="score",
                height=220,
            )
        else:
            clip_count = len(clip_i) + len(clip_t)
            if quality_records:
                st.caption(
                    f"CLIP stage 없음 (quality {len(quality_records)}줄, clip {clip_count}줄). "
                    "이미지 생성 성공 후 CLIP eval이 끝나야 쌓입니다."
                )
            else:
                st.caption("quality.jsonl 데이터 없음 (필터 범위 또는 파일 경로 확인)")


def _render_poster_vlm_section(performance_records: list) -> None:
    _section_header("포스터 VLM")
    _render_section_intro("poster_vlm")
    _render_metric_catalog_table(METRIC_CATALOG["poster_vlm"])

    vlm_inf = filter_records(performance_records, stage="vlm_inference")
    vlm_parse = filter_records(performance_records, stage="vlm_json_parse")
    palette_records = filter_records(performance_records, stage="vlm_palette_reconcile")
    vlm_summary = latency_summary(vlm_inf)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "VLM Inference Latency (P50)",
        format_ms(vlm_summary["p50_ms"]),
        help=METRIC_HELP["VLM Inference Latency (P50)"],
    )
    c2.metric(
        "VLM Inference Latency (P95)",
        format_ms(vlm_summary["p95_ms"]),
        help=METRIC_HELP["VLM Inference Latency (P50)"],
    )
    c3.metric(
        "VLM JSON Parse Success Rate",
        f"{success_rate(vlm_parse)}%",
        help=METRIC_HELP["VLM JSON Parse Success Rate"],
    )

    if palette_records:
        fallback_count = sum(
            1
            for record in palette_records
            if record.get("extra", {}).get("used_rules_fallback") is True
        )
        fallback_rate = round(fallback_count / len(palette_records) * 100, 1)
        c4.metric(
            "Rules Palette Fallback Rate",
            f"{fallback_rate}%",
            help=METRIC_HELP["Rules Palette Fallback Rate"],
        )
    else:
        c4.metric(
            "Rules Palette Fallback Rate",
            "-",
            help=METRIC_HELP["Rules Palette Fallback Rate"],
        )


def _render_raw_expanders(
    performance_records: list,
    quality_records: list,
) -> None:
    with st.expander("원본 JSONL"):
        tab_perf, tab_quality = st.tabs(["performance.jsonl", "quality.jsonl"])
        with tab_perf:
            if performance_records:
                st.dataframe(pd.DataFrame(performance_records), use_container_width=True)
            else:
                st.write("데이터 없음")
        with tab_quality:
            if quality_records:
                st.dataframe(pd.DataFrame(quality_records), use_container_width=True)
            else:
                st.write("데이터 없음")


def render_metrics_dashboard() -> None:
    st.title("성능 · 품질 Metrics")
    st.caption("목차 3섹션 · 지표명 영문 · **?** 에 설명·stage·범위")

    all_performance, all_quality = _load_logs()
    filters = _render_sidebar_filters(all_performance + all_quality)
    performance_records, quality_records = _apply_filters(
        all_performance,
        all_quality,
        filters,
    )

    st.info(f"운영 · 로그: **{_filter_caption(filters, _OPERATIONS_FILTER_KEYS)}**")
    st.info(f"생성 조건: **{_filter_caption(filters, _GENERATION_FILTER_KEYS)}**")

    if not performance_records and not quality_records:
        st.warning("로그가 없거나 필터 조건에 맞는 데이터가 없습니다.")
        return

    total_records = filter_records(performance_records, stage="total_pipeline")

    _render_team_overview(all_performance)

    _render_integrated_api_section(performance_records, total_records)
    st.divider()

    _render_image_generation_section(performance_records, quality_records)
    st.divider()

    _render_poster_vlm_section(performance_records)
    st.divider()

    _render_raw_expanders(performance_records, quality_records)
