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
    single_run_elapsed_ms,
    success_rate,
)
from core.metrics.catalog import (
    CLIP_I_CHART_HELP,
    CLIP_T_CHART_HELP,
    GLOSSARY_MD,
    METRIC_HELP,
    RETRY_CHART_HELP,
    SECTION_HELP,
    VARIANT_CHART_HELP,
)
from core.metrics.config import PERFORMANCE_LOG_PATH, QUALITY_LOG_PATH
from core.metrics.jsonl_loader import (
    apply_dashboard_filters,
    filter_records,
    get_extra,
    get_run_context_for_request,
    load_jsonl,
    unique_extra_values,
    unique_pipeline_request_ids,
)

_FILTER_ALL = "(전체)"

_CORE_METRICS: tuple[tuple[str, str, str], ...] = (
    (
        "통합 파이프라인",
        "total_pipeline",
        METRIC_HELP["Total Pipeline Latency"],
    ),
    (
        "이미지 생성 (inference)",
        "image_provider_generation_sum",
        METRIC_HELP["Image Generation (provider sum)"],
    ),
    (
        "포스터 VLM",
        "vlm_inference",
        METRIC_HELP["VLM Inference Latency"],
    ),
)


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
        options=[_FILTER_ALL] + unique_pipeline_request_ids(all_records)[::-1],
        help="API 1회 생성 = `gen-*` 하나입니다.",
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


def _generation_filter_caption(
    filters: dict[str, str | None],
    all_performance: list,
) -> str:
    explicit = _filter_caption(filters, _GENERATION_FILTER_KEYS)
    if explicit != "전체":
        return explicit

    request_id = filters.get("request_id")
    if not request_id:
        return "전체"

    context = get_run_context_for_request(all_performance, request_id)
    if not context:
        return f"요청 {request_id} (total_pipeline 조건 없음)"

    labels = {
        "image_model_key": "이미지모델",
        "purpose": "목적",
        "food_type": "음식형태",
        "tone": "톤",
    }
    parts = [f"{labels[key]}={context[key]}" for key in _GENERATION_FILTER_KEYS if context.get(key)]
    return " · ".join(parts) if parts else f"요청 {request_id} (total_pipeline 조건 없음)"


def _render_core_metrics(
    performance_records: list,
    *,
    single_run: bool,
) -> None:
    _section_header("성능 요약")

    if single_run:
        cols = st.columns(3)
        for col, (title, stage, help_text) in zip(cols, _CORE_METRICS):
            records = filter_records(performance_records, stage=stage)
            with col:
                st.metric(
                    title,
                    format_ms(single_run_elapsed_ms(records)),
                    help=help_text,
                )
        st.caption(
            "요청 ID 1개 선택 · `total_pipeline`=전체 wall clock · "
            "`image_provider_generation_sum`=생성(inference)만 · VLM=추론"
        )
        return

    cols = st.columns(3)
    for col, (title, stage, help_text) in zip(cols, _CORE_METRICS):
        records = filter_records(performance_records, stage=stage)
        summary = latency_summary(records)
        with col:
            st.markdown(f"**{title}**")
            st.metric("P50", format_ms(summary.get("p50_ms")), help=help_text)
            st.metric("P95", format_ms(summary.get("p95_ms")), help=help_text)
            st.caption(f"runs: **{summary['count']}**")

    st.caption(
        "필터 범위 백분위 · 통합=로드·후처리 포함 · "
        "이미지 생성=3 variant inference 합 · VLM=추론만"
    )


def _render_success_metrics(
    total_records: list,
    *,
    single_run: bool,
) -> None:
    if not total_records:
        return

    if single_run and len(total_records) == 1:
        run = total_records[0]
        partial = get_extra(run, "partial_success")
        st.caption(
            f"이 run · success=**{run.get('success')}** · partial_success=**{partial}**"
        )
        return

    success = success_rate(total_records)
    partial = partial_success_rate(total_records)
    c1, c2 = st.columns(2)
    c1.metric(
        "Pipeline Success Rate",
        f"{success}%" if success is not None else "-",
        help=METRIC_HELP["Pipeline Success Rate"],
    )
    c2.metric(
        "Partial Success Rate",
        f"{partial}%" if partial is not None else "-",
        help=METRIC_HELP["Partial Success Rate"],
    )


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
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            _vertical_bar_chart(
                pd.Series(
                    {row["group"]: row["mean_sec"] for row in rows},
                    name="mean_sec",
                ),
                category_col="group",
                value_col="mean_sec",
                height=220,
            )


def _render_integrated_api_section(
    total_records: list,
) -> None:
    _section_header("통합 API · 분석")
    st.caption("Latency는 상단 **성능 요약** 참고 · 여기서는 run 조건별 비교만 표시합니다.")
    _render_run_context_comparison(total_records)


def _render_image_generation_section(
    performance_records: list,
    quality_records: list,
) -> None:
    _section_header("이미지 · variant / 품질")
    st.caption(
        "시간은 상단 요약(통합·3장 생성·VLM) · "
        "여기서는 variant별·재시도·CLIP만 봅니다."
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
        elif quality_records:
            st.caption("CLIP-I 데이터 없음")
    with right:
        _chart_header("CLIP-T (`clip_t`)", CLIP_T_CHART_HELP, unit="0~1")
        if clip_t_means:
            _vertical_bar_chart(
                pd.Series(clip_t_means, name="score"),
                category_col="variant",
                value_col="score",
                height=220,
            )
        elif quality_records:
            st.caption("CLIP-T 데이터 없음")


def _render_poster_vlm_section(
    performance_records: list,
) -> None:
    _section_header("포스터 VLM · 품질")
    st.caption("VLM 추론 시간은 상단 **성능 요약** · 여기서는 JSON/ palette 성공률만 표시합니다.")

    vlm_parse = filter_records(performance_records, stage="vlm_json_parse")
    palette_records = filter_records(performance_records, stage="vlm_palette_reconcile")

    c1, c2 = st.columns(2)
    c1.metric(
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
        c2.metric(
            "Rules Palette Fallback Rate",
            f"{fallback_rate}%",
            help=METRIC_HELP["Rules Palette Fallback Rate"],
        )
    else:
        c2.metric(
            "Rules Palette Fallback Rate",
            "-",
            help=METRIC_HELP["Rules Palette Fallback Rate"],
        )


def _render_detailed_sections(
    all_performance: list,
    performance_records: list,
    quality_records: list,
    total_records: list,
) -> None:
    with st.expander("상세 지표 (조건별 비교 · variant · CLIP · VLM 품질)", expanded=False):
        st.caption("시간은 상단 **성능 요약** · 아래는 breakdown·품질 지표만.")
        _render_team_overview(all_performance)
        st.divider()
        _render_integrated_api_section(total_records)
        st.divider()
        _render_image_generation_section(performance_records, quality_records)
        st.divider()
        _render_poster_vlm_section(performance_records)


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
    st.title("성능 Metrics")
    st.caption("상단 **성능 요약** 3지표 · **상세 지표** expander에서 breakdown")

    all_performance, all_quality = _load_logs()
    filters = _render_sidebar_filters(all_performance + all_quality)
    performance_records, quality_records = _apply_filters(
        all_performance,
        all_quality,
        filters,
    )

    st.info(f"운영 · 로그: **{_filter_caption(filters, _OPERATIONS_FILTER_KEYS)}**")
    st.info(f"생성 조건: **{_generation_filter_caption(filters, all_performance)}**")

    if not performance_records and not quality_records:
        st.warning("로그가 없거나 필터 조건에 맞는 데이터가 없습니다.")
        return

    total_records = filter_records(performance_records, stage="total_pipeline")
    single_run = bool(filters.get("request_id"))

    _render_core_metrics(performance_records, single_run=single_run)
    _render_success_metrics(total_records, single_run=single_run)

    st.divider()
    _render_detailed_sections(
        all_performance,
        performance_records,
        quality_records,
        total_records,
    )

    st.divider()
    _render_raw_expanders(performance_records, quality_records)
