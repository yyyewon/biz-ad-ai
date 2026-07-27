"""
Metrics dashboard runtime configuration.
"""
from __future__ import annotations

import os
from pathlib import Path


def _default_log_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    dev_logs = repo_root / "backend" / "logs-dev"
    if dev_logs.is_dir():
        return dev_logs
    return repo_root / "backend" / "logs"


LOG_DIR = Path(os.getenv("METRICS_LOG_DIR", str(_default_log_dir())))

PERFORMANCE_LOG_PATH = Path(
    os.getenv(
        "METRICS_PERFORMANCE_LOG_PATH",
        str(LOG_DIR / "performance.jsonl"),
    )
)
QUALITY_LOG_PATH = Path(
    os.getenv(
        "METRICS_QUALITY_LOG_PATH",
        str(LOG_DIR / "quality.jsonl"),
    )
)
