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

STAGE_LABELS: dict[str, str] = {
    "total_pipeline": "Total Pipeline",
    "text_generation": "Text Generation",
    "image_pipeline_total": "Image Pipeline Total",
    "poster_generation": "Poster Generation",
    "variant_generation": "Variant Generation",
    "empty_result_retry": "Empty Result Retry",
    "vlm_inference": "VLM Inference",
    "vlm_json_parse": "VLM JSON Parse",
    "vlm_palette_reconcile": "VLM Palette Reconcile",
    "clip_i": "CLIP-I Similarity",
    "clip_t": "CLIP-T Alignment",
    "model_load": "HF Model Load",
    "inference": "HF Inference",
}
