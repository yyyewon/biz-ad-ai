from types import SimpleNamespace

import pytest

from app.core.exceptions import AppException
from app.services.providers import food_classifier_provider as food_classifier_module
from app.utils import memory_monitor
from app.utils import poster_vlm


def _snapshot(available_gb: float) -> dict[str, float | None]:
    return {
        "ram_available_gb": available_gb,
        "process_rss_gb": 1.25,
        "swap_used_gb": 0.5,
    }


def test_memory_guard_allows_load_at_or_above_threshold():
    measured = _snapshot(6.0)

    result = memory_monitor.ensure_model_load_memory(
        model_name="sd15_controlnet_tile",
        min_available_ram_gb=6.0,
        snapshot=measured,
    )

    assert result is measured


def test_memory_guard_rejects_load_below_threshold():
    with pytest.raises(AppException) as exc_info:
        memory_monitor.ensure_model_load_memory(
            model_name="sd15_controlnet_tile",
            min_available_ram_gb=6.0,
            snapshot=_snapshot(5.999),
        )

    assert exc_info.value.code == "MODEL_LOAD_INSUFFICIENT_SYSTEM_MEMORY"
    assert exc_info.value.detail["ram_available_gb"] == 5.999


def test_memory_guard_can_be_disabled_with_zero_threshold():
    memory_monitor.ensure_model_load_memory(
        model_name="sd15_controlnet_tile",
        min_available_ram_gb=0,
        snapshot=_snapshot(0.1),
    )


def test_memory_snapshot_survives_missing_gpu_and_nvidia_smi(monkeypatch):
    class FakeCuda:
        @staticmethod
        def is_available():
            return False

    class FakeTorch:
        cuda = FakeCuda()

    def missing_nvidia_smi(*_args, **_kwargs):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(memory_monitor.subprocess, "check_output", missing_nvidia_smi)

    snapshot = memory_monitor.collect_memory_snapshot(torch_module=FakeTorch())

    assert "ram_total_gb" in snapshot
    assert "process_rss_gb" in snapshot
    assert snapshot["gpu_free_gb"] is None
    assert snapshot["nvidia_smi_used_gb"] is None


def test_poster_vlm_guard_runs_before_transformers_loader(monkeypatch):
    monkeypatch.setattr(poster_vlm, "_MODEL", None)
    monkeypatch.setattr(poster_vlm, "_PROCESSOR", None)
    monkeypatch.setattr(
        poster_vlm,
        "get_settings",
        lambda: SimpleNamespace(model_load_min_available_ram_gb=6.0),
    )
    monkeypatch.setattr(
        poster_vlm,
        "log_model_memory_snapshot",
        lambda *_args, **_kwargs: _snapshot(5.0),
    )

    with pytest.raises(AppException) as exc_info:
        poster_vlm._get_vlm_model(model_id="test/poster-vlm", settings={})

    assert exc_info.value.code == "MODEL_LOAD_INSUFFICIENT_SYSTEM_MEMORY"
    assert poster_vlm._MODEL is None


def test_food_classifier_guard_runs_before_transformers_loader(monkeypatch):
    provider = food_classifier_module.FoodClassifierProvider()
    monkeypatch.setattr(
        food_classifier_module,
        "get_settings",
        lambda: SimpleNamespace(model_load_min_available_ram_gb=6.0),
    )
    monkeypatch.setattr(
        food_classifier_module,
        "log_model_memory_snapshot",
        lambda *_args, **_kwargs: _snapshot(5.0),
    )

    with pytest.raises(AppException) as exc_info:
        provider._ensure_model_loaded()

    assert exc_info.value.code == "MODEL_LOAD_INSUFFICIENT_SYSTEM_MEMORY"
    assert provider._classifier is None
