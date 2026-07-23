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


def unique_profile_values(
    records: list[dict[str, Any]],
    *,
    stage: str = "total_pipeline",
) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    for record in filter_records(records, stage=stage):
        value = record.get("profile")
        if not value:
            continue
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        ordered.append(text)

    return ordered


def filter_by_run_context(
    records: list[dict[str, Any]],
    *,
    profile: str | None = None,
    purpose: str | None = None,
    tone: str | None = None,
    food_type: str | None = None,
    text_model_key: str | None = None,
    image_model_key: str | None = None,
) -> list[dict[str, Any]]:
    """
    total_pipeline extra의 생성 조건으로 request_id를 좁힌 뒤
    같은 요청의 stage·quality 로그까지 함께 반환한다.
    """

    run_filters = {
        "profile": profile,
        "purpose": purpose,
        "tone": tone,
        "food_type": food_type,
        "text_model_key": text_model_key,
        "image_model_key": image_model_key,
    }
    active = {key: value for key, value in run_filters.items() if value}

    if not active:
        return records

    matching_request_ids: set[str] = set()

    for record in filter_records(records, stage="total_pipeline"):
        if profile is not None and record.get("profile") != profile:
            continue
        if purpose is not None and get_extra(record, "purpose") != purpose:
            continue
        if tone is not None and get_extra(record, "tone") != tone:
            continue
        if food_type is not None and get_extra(record, "food_type") != food_type:
            continue
        if text_model_key is not None and get_extra(record, "text_model_key") != text_model_key:
            continue
        if image_model_key is not None and get_extra(record, "image_model_key") != image_model_key:
            continue

        request_id = record.get("request_id")
        if request_id:
            matching_request_ids.add(str(request_id))

    if not matching_request_ids:
        return []

    return [
        record
        for record in records
        if str(record.get("request_id")) in matching_request_ids
    ]


def get_extra(record: dict[str, Any], key: str, default: Any = None) -> Any:
    extra = record.get("extra")
    if not isinstance(extra, dict):
        return default
    return extra.get(key, default)
