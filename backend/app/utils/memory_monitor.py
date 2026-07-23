from __future__ import annotations

import subprocess
import sys
from typing import Any

from loguru import logger

from app.core import error_constants as errors
from app.core.exceptions import AppException


_BYTES_PER_GB = 1024**3
_MIB_PER_GB = 1024


def _to_gb(value: int | float | None) -> float | None:
    if value is None:
        return None
    return round(float(value) / _BYTES_PER_GB, 3)


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

    return {
        **_system_memory_snapshot(),
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
        "ram_available_gb={} | swap_used_gb={} | gpu_free_gb={} | gpu_total_gb={} | "
        "nvidia_smi_used_gb={} | nvidia_smi_total_gb={}",
        stage,
        model_name,
        snapshot["process_rss_gb"],
        snapshot["ram_available_gb"],
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
    snapshot: dict[str, float | None] | None = None,
    torch_module: Any | None = None,
) -> dict[str, float | None]:
    """Reject a model load before allocation when host available RAM is too low."""

    measured = snapshot or collect_memory_snapshot(torch_module=torch_module)
    threshold = float(min_available_ram_gb)
    available = measured.get("ram_available_gb")

    if threshold <= 0 or available is None or available >= threshold:
        return measured

    logger.error(
        "model_load_rejected | reason=insufficient_system_memory | model_name={} | "
        "ram_available_gb={} | required_ram_gb={} | process_rss_gb={} | swap_used_gb={}",
        model_name,
        available,
        round(threshold, 3),
        measured.get("process_rss_gb"),
        measured.get("swap_used_gb"),
    )
    raise AppException(
        errors.MODEL_LOAD_INSUFFICIENT_SYSTEM_MEMORY,
        detail={
            "model_name": model_name,
            "ram_available_gb": available,
            "required_ram_gb": round(threshold, 3),
            "process_rss_gb": measured.get("process_rss_gb"),
            "swap_used_gb": measured.get("swap_used_gb"),
        },
    )
