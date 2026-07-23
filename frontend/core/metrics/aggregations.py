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
        return f"{value / 1000:.1f}초"

    return f"{value:.0f}ms"
