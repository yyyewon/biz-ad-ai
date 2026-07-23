"""
JSONL performance / quality log loader for the metrics dashboard.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """
    Read a JSONL file and return parsed records. Skips blank or invalid lines.
    """

    if not path.is_file():
        return []

    records: list[dict[str, Any]] = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)

    return records


def filter_records(
    records: list[dict[str, Any]],
    *,
    stage: str | None = None,
    metric_id: str | None = None,
    request_id: str | None = None,
    pipeline: str | None = None,
    source_user: str | None = None,
    backend_port: str | None = None,
    frontend_port: str | None = None,
    deploy_env: str | None = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []

    for record in records:
        if stage is not None and record.get("stage") != stage:
            continue
        if metric_id is not None and record.get("metric_id") != metric_id:
            continue
        if request_id is not None and record.get("request_id") != request_id:
            continue
        if pipeline is not None and record.get("pipeline") != pipeline:
            continue
        if source_user is not None and get_extra(record, "source_user") != source_user:
            continue
        if backend_port is not None and str(get_extra(record, "backend_port")) != backend_port:
            continue
        if frontend_port is not None and str(get_extra(record, "frontend_port")) != frontend_port:
            continue
        if deploy_env is not None and get_extra(record, "deploy_env") != deploy_env:
            continue
        filtered.append(record)

    return filtered


def unique_extra_values(records: list[dict[str, Any]], key: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    for record in records:
        value = get_extra(record, key)
        if value is None:
            continue
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        ordered.append(text)

    return ordered


def unique_request_ids(records: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    for record in records:
        request_id = record.get("request_id")
        if not request_id or request_id in seen:
            continue
        seen.add(str(request_id))
        ordered.append(str(request_id))

    return ordered


def get_extra(record: dict[str, Any], key: str, default: Any = None) -> Any:
    extra = record.get("extra")
    if not isinstance(extra, dict):
        return default
    return extra.get(key, default)
