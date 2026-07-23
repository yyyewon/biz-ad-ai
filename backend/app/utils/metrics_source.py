"""
JSONL metric 출처(팀원·포트·환경) 컨텍스트.

Docker dev compose에서 METRICS_* 환경변수로 주입한다.
"""
from __future__ import annotations

import os
from typing import Any


def get_metrics_source_context() -> dict[str, str]:
    context: dict[str, str] = {}

    source_user = os.getenv("METRICS_SOURCE_USER", "").strip()
    backend_port = os.getenv("METRICS_BACKEND_PORT", "").strip()
    frontend_port = os.getenv("METRICS_FRONTEND_PORT", "").strip()
    deploy_env = os.getenv("METRICS_DEPLOY_ENV", "").strip() or "dev"

    if source_user:
        context["source_user"] = source_user
    if backend_port:
        context["backend_port"] = backend_port
    if frontend_port:
        context["frontend_port"] = frontend_port
    if context:
        context["deploy_env"] = deploy_env

    return context


def merge_metrics_source_extra(extra: dict[str, Any] | None) -> dict[str, Any]:
    source = get_metrics_source_context()
    if not source:
        return dict(extra or {})

    merged = dict(extra or {})
    for key, value in source.items():
        merged.setdefault(key, value)
    return merged


def attach_source_context(metric: dict[str, Any]) -> dict[str, Any]:
    source = get_metrics_source_context()
    if not source:
        return metric

    enriched = dict(metric)
    enriched["extra"] = merge_metrics_source_extra(enriched.get("extra"))
    return enriched
