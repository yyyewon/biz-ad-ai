from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from app.core import error_constants as errors
from app.core.exceptions import AppException


_BYTES_PER_GB = 1024**3
_MIB_PER_GB = 1024
_CGROUP_V2_MEMORY_MAX = "/sys/fs/cgroup/memory.max"
_CGROUP_V2_MEMORY_CURRENT = "/sys/fs/cgroup/memory.current"
_CGROUP_V1_MEMORY_LIMIT = "/sys/fs/cgroup/memory/memory.limit_in_bytes"
_CGROUP_V1_MEMORY_USAGE = "/sys/fs/cgroup/memory/memory.usage_in_bytes"
_CGROUP_V1_UNLIMITED_THRESHOLD_BYTES = 1 << 60


def _to_gb(value: int | float | None) -> float | None:
    if value is None:
        return None
    return round(float(value) / _BYTES_PER_GB, 3)


def _read_text_file(path: str) -> str | None:
    """Read a small optional system file without making diagnostics fatal."""

    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _parse_non_negative_bytes(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _cgroup_values(*, limit_bytes: int | None, current_bytes: int) -> dict[str, float | None]:
    available_bytes = (
        max(limit_bytes - current_bytes, 0) if limit_bytes is not None else None
    )
    return {
        "cgroup_memory_limit_gb": _to_gb(limit_bytes),
        "cgroup_memory_current_gb": _to_gb(current_bytes),
        "cgroup_memory_available_gb": _to_gb(available_bytes),
    }


def _read_cgroup_v2_memory() -> dict[str, float | None] | None:
    """Read cgroup v2 memory values, recognizing ``memory.max=max`` as unlimited."""

    limit_text = _read_text_file(_CGROUP_V2_MEMORY_MAX)
    current_bytes = _parse_non_negative_bytes(
        _read_text_file(_CGROUP_V2_MEMORY_CURRENT)
    )
    if limit_text is None or current_bytes is None:
        return None

    if limit_text == "max":
        return _cgroup_values(limit_bytes=None, current_bytes=current_bytes)

    limit_bytes = _parse_non_negative_bytes(limit_text)
    if limit_bytes is None:
        return None
    return _cgroup_values(limit_bytes=limit_bytes, current_bytes=current_bytes)


def _read_cgroup_v1_memory() -> dict[str, float | None] | None:
    """Read cgroup v1 memory values and normalize its huge unlimited sentinel."""

    limit_bytes = _parse_non_negative_bytes(_read_text_file(_CGROUP_V1_MEMORY_LIMIT))
    current_bytes = _parse_non_negative_bytes(_read_text_file(_CGROUP_V1_MEMORY_USAGE))
    if limit_bytes is None or current_bytes is None:
        return None

    normalized_limit = (
        None
        if limit_bytes >= _CGROUP_V1_UNLIMITED_THRESHOLD_BYTES
        else limit_bytes
    )
    return _cgroup_values(limit_bytes=normalized_limit, current_bytes=current_bytes)


def _cgroup_memory_snapshot() -> dict[str, float | None]:
    """Prefer a valid cgroup v2 snapshot, then fall back to cgroup v1."""

    snapshot = _read_cgroup_v2_memory()
    if snapshot is None:
        snapshot = _read_cgroup_v1_memory()
    return snapshot or {
        "cgroup_memory_limit_gb": None,
        "cgroup_memory_current_gb": None,
        "cgroup_memory_available_gb": None,
    }


def _system_memory_snapshot() -> dict[str, float | None]:
    snapshot: dict[str, float | None] = {
        "ram_total_gb": None,
        "ram_available_gb": None,
        "ram_used_gb": None,
        "ram_percent": None,
        "swap_total_gb": None,
        "swap_used_gb": None,
        "swap_free_gb": None,
        "process_rss_gb": None,
        "process_vms_gb": None,
    }

    try:
        import psutil

        virtual_memory = psutil.virtual_memory()
        swap_memory = psutil.swap_memory()
        process_memory = psutil.Process().memory_info()
        snapshot.update(
            {
                "ram_total_gb": _to_gb(virtual_memory.total),
                "ram_available_gb": _to_gb(virtual_memory.available),
                "ram_used_gb": _to_gb(virtual_memory.used),
                "ram_percent": round(float(virtual_memory.percent), 3),
                "swap_total_gb": _to_gb(swap_memory.total),
                "swap_used_gb": _to_gb(swap_memory.used),
                "swap_free_gb": _to_gb(swap_memory.free),
                "process_rss_gb": _to_gb(process_memory.rss),
                "process_vms_gb": _to_gb(process_memory.vms),
            }
        )
    except Exception:
        pass

    return snapshot


def _torch_memory_snapshot(torch_module: Any | None) -> dict[str, float | None]:
    snapshot: dict[str, float | None] = {
        "gpu_memory_allocated_gb": None,
        "gpu_memory_reserved_gb": None,
        "gpu_peak_allocated_gb": None,
        "gpu_peak_reserved_gb": None,
        "gpu_free_gb": None,
        "gpu_total_gb": None,
    }

    resolved_torch = torch_module or sys.modules.get("torch")
    try:
        cuda = getattr(resolved_torch, "cuda", None)
        if cuda is None or not cuda.is_available():
            return snapshot

        free_bytes, total_bytes = cuda.mem_get_info()
        snapshot.update(
            {
                "gpu_memory_allocated_gb": _to_gb(cuda.memory_allocated()),
                "gpu_memory_reserved_gb": _to_gb(cuda.memory_reserved()),
                "gpu_peak_allocated_gb": _to_gb(cuda.max_memory_allocated()),
                "gpu_peak_reserved_gb": _to_gb(cuda.max_memory_reserved()),
                "gpu_free_gb": _to_gb(free_bytes),
                "gpu_total_gb": _to_gb(total_bytes),
            }
        )
    except Exception:
        pass

    return snapshot


def _nvidia_smi_memory_snapshot() -> dict[str, float | None]:
    snapshot: dict[str, float | None] = {
        "nvidia_smi_used_gb": None,
        "nvidia_smi_total_gb": None,
    }

    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        rows = [line.strip() for line in output.splitlines() if line.strip()]
        values = [tuple(float(value.strip()) for value in row.split(",", 1)) for row in rows]
        if values:
            snapshot["nvidia_smi_used_gb"] = round(
                sum(used_mib for used_mib, _ in values) / _MIB_PER_GB,
                3,
            )
            snapshot["nvidia_smi_total_gb"] = round(
                sum(total_mib for _, total_mib in values) / _MIB_PER_GB,
                3,
            )
    except Exception:
        pass

    return snapshot


def collect_memory_snapshot(*, torch_module: Any | None = None) -> dict[str, float | None]:
    """Return memory metrics without failing when optional GPU tools are absent."""

    system_snapshot = _system_memory_snapshot()
    cgroup_snapshot = _cgroup_memory_snapshot()
    available_candidates = [
        value
        for value in (
            system_snapshot["ram_available_gb"],
            cgroup_snapshot["cgroup_memory_available_gb"],
        )
        if value is not None
    ]
    effective_available = min(available_candidates) if available_candidates else None

    return {
        **system_snapshot,
        **cgroup_snapshot,
        "effective_available_ram_gb": effective_available,
        **_torch_memory_snapshot(torch_module),
        **_nvidia_smi_memory_snapshot(),
    }


def log_model_memory_snapshot(
    stage: str,
    *,
    model_name: str,
    torch_module: Any | None = None,
) -> dict[str, float | None]:
    """Collect and log the compact metrics used to diagnose model-load OOMs."""

    snapshot = collect_memory_snapshot(torch_module=torch_module)
    logger.info(
        "model_memory_snapshot | stage={} | model_name={} | process_rss_gb={} | "
        "ram_available_gb={} | cgroup_memory_limit_gb={} | "
        "cgroup_memory_current_gb={} | cgroup_memory_available_gb={} | "
        "effective_available_ram_gb={} | swap_used_gb={} | gpu_free_gb={} | gpu_total_gb={} | "
        "nvidia_smi_used_gb={} | nvidia_smi_total_gb={}",
        stage,
        model_name,
        snapshot["process_rss_gb"],
        snapshot["ram_available_gb"],
        snapshot["cgroup_memory_limit_gb"],
        snapshot["cgroup_memory_current_gb"],
        snapshot["cgroup_memory_available_gb"],
        snapshot["effective_available_ram_gb"],
        snapshot["swap_used_gb"],
        snapshot["gpu_free_gb"],
        snapshot["gpu_total_gb"],
        snapshot["nvidia_smi_used_gb"],
        snapshot["nvidia_smi_total_gb"],
    )
    return snapshot


def ensure_model_load_memory(
    *,
    model_name: str,
    min_available_ram_gb: float,
    load_stage: str = "before_model_load",
    snapshot: dict[str, float | None] | None = None,
    torch_module: Any | None = None,
) -> dict[str, float | None]:
    """Reject a model load when effective container memory is below the threshold."""

    measured = (
        snapshot
        if snapshot is not None
        else collect_memory_snapshot(torch_module=torch_module)
    )
    threshold = float(min_available_ram_gb)
    effective_available = measured.get("effective_available_ram_gb")
    host_available = measured.get("ram_available_gb")
    available = (
        effective_available if effective_available is not None else host_available
    )

    if threshold <= 0 or available is None or available >= threshold:
        return measured

    logger.error(
        "model_load_rejected | reason=insufficient_system_memory | model_name={} | "
        "load_stage={} | ram_available_gb={} | cgroup_memory_limit_gb={} | "
        "cgroup_memory_current_gb={} | cgroup_memory_available_gb={} | "
        "effective_available_ram_gb={} | required_ram_gb={} | process_rss_gb={} | "
        "swap_used_gb={}",
        model_name,
        load_stage,
        host_available,
        measured.get("cgroup_memory_limit_gb"),
        measured.get("cgroup_memory_current_gb"),
        measured.get("cgroup_memory_available_gb"),
        effective_available,
        round(threshold, 3),
        measured.get("process_rss_gb"),
        measured.get("swap_used_gb"),
    )
    raise AppException(
        errors.MODEL_LOAD_INSUFFICIENT_SYSTEM_MEMORY,
        detail={
            "model_name": model_name,
            "load_stage": load_stage,
            "ram_available_gb": host_available,
            "cgroup_memory_limit_gb": measured.get("cgroup_memory_limit_gb"),
            "cgroup_memory_current_gb": measured.get("cgroup_memory_current_gb"),
            "cgroup_memory_available_gb": measured.get("cgroup_memory_available_gb"),
            "effective_available_ram_gb": effective_available,
            "required_ram_gb": round(threshold, 3),
            "process_rss_gb": measured.get("process_rss_gb"),
            "swap_used_gb": measured.get("swap_used_gb"),
        },
    )
