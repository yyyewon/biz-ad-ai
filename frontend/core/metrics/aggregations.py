"""
Aggregate helpers for metrics dashboard charts and summary cards.
"""
from __future__ import annotations

from statistics import mean
from typing import Any

from core.metrics.jsonl_loader import get_extra


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None

    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    rank = (len(ordered) - 1) * (pct / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def latency_summary(records: list[dict[str, Any]]) -> dict[str, float | int | None]:
    values = [
        float(record["elapsed_ms"])
        for record in records
        if record.get("elapsed_ms") is not None
    ]

    if not values:
        return {"count": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None}

    return {
        "count": len(values),
        "mean_ms": round(mean(values), 1),
        "p50_ms": round(percentile(values, 50) or 0, 1),
        "p95_ms": round(percentile(values, 95) or 0, 1),
    }


def success_rate(records: list[dict[str, Any]]) -> float | None:
    if not records:
        return None

    successes = sum(1 for record in records if record.get("success") is True)
    return round(successes / len(records) * 100, 1)


def partial_success_rate(records: list[dict[str, Any]]) -> float | None:
    if not records:
        return None

    partials = sum(
        1
        for record in records
        if get_extra(record, "partial_success") is True
    )
    return round(partials / len(records) * 100, 1)


def group_mean_elapsed_ms(
    records: list[dict[str, Any]],
    group_key: str,
) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}

    for record in records:
        group_value = get_extra(record, group_key) or record.get(group_key) or "unknown"
        elapsed_ms = record.get("elapsed_ms")
        if elapsed_ms is None:
            continue
        key = str(group_value)
        buckets.setdefault(key, []).append(float(elapsed_ms))

    return {
        key: round(mean(values), 1)
        for key, values in sorted(buckets.items())
    }


def group_mean_score(
    records: list[dict[str, Any]],
    group_key: str = "variant",
) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}

    for record in records:
        score = get_extra(record, "score")
        if score is None:
            continue
        group_value = get_extra(record, group_key) or "unknown"
        key = str(group_value)
        buckets.setdefault(key, []).append(float(score))

    return {
        key: round(mean(values), 4)
        for key, values in sorted(buckets.items())
    }


def count_by_extra(
    records: list[dict[str, Any]],
    group_key: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}

    for record in records:
        group_value = get_extra(record, group_key) or "unknown"
        key = str(group_value)
        counts[key] = counts.get(key, 0) + 1

    return dict(sorted(counts.items()))


def format_ms(value: float | None) -> str:
    if value is None:
        return "-"

    if value >= 60_000:
        minutes = int(value // 60_000)
        seconds = (value % 60_000) / 1000
        return f"{minutes}분 {seconds:.1f}초"

    if value >= 1000:
        return f"{value / 1000:.2f}초"

    return f"{value:.0f}ms"


def single_run_elapsed_ms(records: list[dict[str, Any]]) -> float | None:
    """단일 request_id 필터 시 해당 stage의 실제 elapsed_ms (1건 또는 max)."""

    values = [
        float(record["elapsed_ms"])
        for record in records
        if record.get("elapsed_ms") is not None
    ]
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return max(values)


def latency_metric_labels(
    base: str,
    *,
    single_run: bool,
    count: int,
) -> tuple[str, str | None]:
    """
    단일 request_id 필터: P50/P95 대신 이 run의 실제 elapsed_ms 라벨.
    같은 run에 stage 로그가 여러 건이면 중간/최대.
    """

    if single_run and count == 1:
        return f"{base} (이 run)", None
    if single_run and count > 1:
        return f"{base} (중간)", f"{base} (최대)"
    return f"{base} (P50)", f"{base} (P95)"


def render_latency_metric_pair(
    container_left,
    container_right,
    summary: dict[str, float | int | None],
    *,
    base_label: str,
    single_run: bool,
    records: list[dict[str, Any]] | None = None,
    help_text: str | None = None,
) -> None:
    count = int(summary.get("count") or 0)
    if single_run:
        elapsed = single_run_elapsed_ms(records or [])
        container_left.metric(
            base_label,
            format_ms(elapsed),
            help=help_text,
        )
        return

    left_label, right_label = latency_metric_labels(
        base_label,
        single_run=False,
        count=count,
    )
    container_left.metric(
        left_label,
        format_ms(summary.get("p50_ms")),
        help=help_text,
    )
    container_right.metric(
        right_label,
        format_ms(summary.get("p95_ms")),
        help=help_text,
    )


def ms_to_sec(value: float) -> float:
    """Chart axis용 — ms → sec (1 decimal)."""
    return round(value / 1000, 1)


def dict_ms_to_sec(values: dict[str, float]) -> dict[str, float]:
    return {key: ms_to_sec(val) for key, val in values.items()}
