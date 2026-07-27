"""Shared request_id format for API runs and JSONL metrics."""

from __future__ import annotations

import uuid


def new_run_request_id() -> str:
    """Return a pipeline-scoped request id (`gen-*`)."""

    return f"gen-{uuid.uuid4().hex[:8]}"


def resolve_run_request_id(request_id: str | None) -> str:
    """Use the caller's run id or allocate a new `gen-*` id."""

    if request_id and str(request_id).strip():
        return str(request_id).strip()
    return new_run_request_id()
