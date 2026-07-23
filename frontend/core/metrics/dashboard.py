"""
Metrics dashboard UI (metrics_app.py entry).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.metrics.aggregations import (
    count_by_extra,
    format_ms,
    group_mean_elapsed_ms,
    group_mean_score,
    latency_summary,
    partial_success_rate,
    success_rate,
)
from core.metrics.config import PERFORMANCE_LOG_PATH, QUALITY_LOG_PATH, STAGE_LABELS
from core.metrics.jsonl_loader import (
    filter_records,
    load_jsonl,
    unique_extra_values,
    unique_request_ids,
)


@st.cache_data(ttl=30)
def _load_logs() -> tuple[list, list]:
    return load_jsonl(PERFORMANCE_LOG_PATH), load_jsonl(QUALITY_LOG_PATH)


def _render_controls() -> dict[str, str | None]:
    st.caption(f"performance: `{PERFORMANCE_LOG_PATH}`")
    st.caption(f"quality: `{QUALITY_LOG_PATH}`")

    if st.button("새로고침", width="stretch"):
        _load_logs.clear()

    performance_records, quality_records = _load_logs()
    all_records = performance_records + quality_records

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        source_user = st.selectbox(
            "source_user",
            options=["(전체)"] + unique_extra_values(all_records, "source_user"),
        )
    with col2:
        backend_port = st.selectbox(
            "backend_port",
            options=["(전체)"] + unique_extra_values(all_records, "backend_port"),
        )
    with col3:
        frontend_port = st.selectbox(
            "frontend_port",
            options=["(전체)"] + unique_extra_values(all_records, "frontend_port"),
        )
    with col4:
        deploy_env = st.selectbox(
            "deploy_env",
            options=["(전체)"] + unique_extra_values(all_records, "deploy_env"),
        )

    request_ids = unique_request_ids(all_records)
    selected_request = st.selectbox(
        "request_id",
        options=["(전체)"] + request_ids[::-1],
    )

    def _pick(value: str) -> str | None:
        return None if value == "(전체)" else value

    return {
        "request_id": _pick(selected_request),
        "source_user": _pick(source_user),
        "backend_port": _pick(backend_port),
        "frontend_port": _pick(frontend_port),
        "deploy_env": _pick(deploy_env),
    }


def _apply_filters(records: list, filters: dict[str, str | None]) -> list:
    return filter_records(
        records,
        request_id=filters.get("request_id"),
        source_user=filters.get("source_user"),
        backend_port=filters.get("backend_port"),
        frontend_port=filters.get("frontend_port"),
        deploy_env=filters.get("deploy_env"),
    )


def _metric_cards(total_records: list) -> None:
    summary = latency_summary(total_records)
    col1, col2, col3, col4 = st.columns(4)

    col1.metric("생성 run 수", summary["count"])
    col2.metric("P50 latency", format_ms(summary["p50_ms"]))
    col3.metric("P95 latency", format_ms(summary["p95_ms"]))
    success = success_rate(total_records)
    col4.metric("Success rate", f"{success}%" if success is not None else "-")


def render_metrics_dashboard() -> None:
    st.title("Metrics")
    st.caption("JSONL performance / quality 지표 대시보드")

    filters = _render_controls()
    all_performance, all_quality = _load_logs()
    performance_records = _apply_filters(all_performance, filters)
    quality_records = _apply_filters(all_quality, filters)

    if not performance_records and not quality_records:
        st.warning("JSONL 로그 파일이 없거나 필터 조건에 맞는 데이터가 없어요.")
        return

    source_counts = count_by_extra(
        filter_records(all_performance, stage="total_pipeline"),
        "source_user",
    )
    if source_counts:
        st.caption("팀 전체 run 수 (total_pipeline, source_user)")
        st.bar_chart(pd.Series(source_counts))

    total_records = filter_records(performance_records, stage="total_pipeline")
    st.subheader("Overview")
    _metric_cards(total_records)

    st.divider()
    st.subheader("Latency")

    left, right = st.columns(2)

    with left:
        st.markdown("**Total Pipeline (P50/P95)**")
        summary = latency_summary(total_records)
        st.write(
            {
                "count": summary["count"],
                "mean": format_ms(summary["mean_ms"]),
                "p50": format_ms(summary["p50_ms"]),
                "p95": format_ms(summary["p95_ms"]),
            }
        )

        variant_records = filter_records(
            performance_records,
            stage="variant_generation",
        )
        variant_means = group_mean_elapsed_ms(variant_records, "variant")
        if variant_means:
            st.markdown("**Variant Generation (mean ms)**")
            st.bar_chart(pd.Series(variant_means))

    with right:
        text_records = filter_records(performance_records, stage="text_generation")
        text_summary = latency_summary(text_records)
        st.markdown("**Text Generation**")
        st.write(
            {
                "count": text_summary["count"],
                "p50": format_ms(text_summary["p50_ms"]),
                "p95": format_ms(text_summary["p95_ms"]),
            }
        )

        vlm_records = filter_records(performance_records, stage="vlm_inference")
        vlm_summary = latency_summary(vlm_records)
        st.markdown("**VLM Inference**")
        st.write(
            {
                "count": vlm_summary["count"],
                "p50": format_ms(vlm_summary["p50_ms"]),
                "p95": format_ms(vlm_summary["p95_ms"]),
            }
        )

    retry_records = filter_records(performance_records, stage="empty_result_retry")
    if retry_records:
        st.markdown("**Empty Result Retry (attempt count)**")
        st.bar_chart(pd.Series(count_by_extra(retry_records, "attempt")))

    st.divider()
    st.subheader("Success / VLM")

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Pipeline success", f"{success_rate(total_records)}%")
    col_b.metric("Partial success", f"{partial_success_rate(total_records)}%")

    vlm_parse = filter_records(performance_records, stage="vlm_json_parse")
    col_c.metric("VLM JSON parse success", f"{success_rate(vlm_parse)}%")

    palette_records = filter_records(performance_records, stage="vlm_palette_reconcile")
    if palette_records:
        fallback_count = sum(
            1
            for record in palette_records
            if record.get("extra", {}).get("used_rules_fallback") is True
        )
        fallback_rate = round(fallback_count / len(palette_records) * 100, 1)
        st.metric("Palette rules fallback rate", f"{fallback_rate}%")

    st.divider()
    st.subheader("Quality (CLIP)")

    if not quality_records:
        st.info("quality.jsonl 데이터가 아직 없어요. 생성 완료 후 1~2분 뒤 새로고침해 주세요.")
    else:
        clip_i = filter_records(quality_records, stage="clip_i")
        clip_t = filter_records(quality_records, stage="clip_t")

        q_left, q_right = st.columns(2)
        with q_left:
            clip_i_means = group_mean_score(clip_i)
            if clip_i_means:
                st.markdown("**CLIP-I mean score by variant**")
                st.bar_chart(pd.Series(clip_i_means))

        with q_right:
            clip_t_means = group_mean_score(clip_t)
            if clip_t_means:
                st.markdown("**CLIP-T mean score by variant**")
                st.bar_chart(pd.Series(clip_t_means))

    st.divider()
    st.subheader("Raw Records")

    tab_perf, tab_quality = st.tabs(["performance.jsonl", "quality.jsonl"])

    with tab_perf:
        if performance_records:
            df = pd.DataFrame(performance_records)
            if "stage" in df.columns:
                df["stage_label"] = df["stage"].map(STAGE_LABELS).fillna(df["stage"])
            st.dataframe(df, width="stretch")
        else:
            st.write("데이터 없음")

    with tab_quality:
        if quality_records:
            st.dataframe(pd.DataFrame(quality_records), width="stretch")
        else:
            st.write("데이터 없음")
