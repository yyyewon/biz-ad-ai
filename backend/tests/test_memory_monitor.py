from types import SimpleNamespace

import pytest

from app.core.exceptions import AppException
from app.services.providers import food_classifier_provider as food_classifier_module
from app.utils import memory_monitor
from app.utils import poster_vlm


_GIB = 1024**3


def _snapshot(available_gb: float) -> dict[str, float | None]:
    return {
        "ram_available_gb": available_gb,
        "process_rss_gb": 1.25,
        "swap_used_gb": 0.5,
    }


def _mock_cgroup_files(monkeypatch, values: dict[str, str | None]) -> None:
    monkeypatch.setattr(
        memory_monitor,
        "_read_text_file",
        lambda path: values.get(path),
    )


def test_cgroup_v2_reads_limit_current_and_available(monkeypatch):
    _mock_cgroup_files(
        monkeypatch,
        {
            memory_monitor._CGROUP_V2_MEMORY_MAX: str(12 * _GIB),
            memory_monitor._CGROUP_V2_MEMORY_CURRENT: str(3 * _GIB),
            memory_monitor._CGROUP_V2_MEMORY_STAT: (
                f"anon {_GIB}\nfile {2 * _GIB}\n"
                f"inactive_file {int(1.5 * _GIB)}\nactive_file {int(0.5 * _GIB)}\n"
            ),
        },
    )

    assert memory_monitor._read_cgroup_v2_memory() == {
        "cgroup_memory_limit_gb": 12.0,
        "cgroup_memory_current_gb": 3.0,
        "cgroup_memory_available_gb": 11.0,
        "cgroup_inactive_file_gb": 1.5,
        "cgroup_active_file_gb": 0.5,
        "cgroup_reclaimable_file_gb": 2.0,
        "cgroup_working_set_gb": 1.0,
    }


def test_cgroup_v2_treats_max_as_unlimited(monkeypatch):
    _mock_cgroup_files(
        monkeypatch,
        {
            memory_monitor._CGROUP_V2_MEMORY_MAX: "max",
            memory_monitor._CGROUP_V2_MEMORY_CURRENT: str(2 * _GIB),
        },
    )

    assert memory_monitor._read_cgroup_v2_memory() == {
        "cgroup_memory_limit_gb": None,
        "cgroup_memory_current_gb": 2.0,
        "cgroup_memory_available_gb": None,
    }


@pytest.mark.parametrize("limit,current", [(None, None), ("invalid", "1")])
def test_cgroup_v2_invalid_or_missing_files_return_none(monkeypatch, limit, current):
    _mock_cgroup_files(
        monkeypatch,
        {
            memory_monitor._CGROUP_V2_MEMORY_MAX: limit,
            memory_monitor._CGROUP_V2_MEMORY_CURRENT: current,
        },
    )

    assert memory_monitor._read_cgroup_v2_memory() is None


def test_cgroup_v2_clamps_available_to_zero(monkeypatch):
    _mock_cgroup_files(
        monkeypatch,
        {
            memory_monitor._CGROUP_V2_MEMORY_MAX: str(4 * _GIB),
            memory_monitor._CGROUP_V2_MEMORY_CURRENT: str(5 * _GIB),
        },
    )

    assert memory_monitor._read_cgroup_v2_memory()["cgroup_memory_available_gb"] == 0


def test_cgroup_v1_reads_limit_usage_and_available(monkeypatch):
    _mock_cgroup_files(
        monkeypatch,
        {
            memory_monitor._CGROUP_V1_MEMORY_LIMIT: str(12 * _GIB),
            memory_monitor._CGROUP_V1_MEMORY_USAGE: str(4 * _GIB),
        },
    )

    assert memory_monitor._read_cgroup_v1_memory() == {
        "cgroup_memory_limit_gb": 12.0,
        "cgroup_memory_current_gb": 4.0,
        "cgroup_memory_available_gb": 8.0,
    }


def test_cgroup_v1_treats_huge_limit_as_unlimited(monkeypatch):
    _mock_cgroup_files(
        monkeypatch,
        {
            memory_monitor._CGROUP_V1_MEMORY_LIMIT: str(1 << 62),
            memory_monitor._CGROUP_V1_MEMORY_USAGE: str(_GIB),
        },
    )

    assert memory_monitor._read_cgroup_v1_memory() == {
        "cgroup_memory_limit_gb": None,
        "cgroup_memory_current_gb": 1.0,
        "cgroup_memory_available_gb": None,
    }


def test_cgroup_v1_read_failure_returns_none(monkeypatch):
    _mock_cgroup_files(monkeypatch, {})

    assert memory_monitor._read_cgroup_v1_memory() is None


def test_valid_cgroup_v2_snapshot_takes_priority_over_v1(monkeypatch):
    v2 = {
        "cgroup_memory_limit_gb": 12.0,
        "cgroup_memory_current_gb": 2.0,
        "cgroup_memory_available_gb": 10.0,
    }
    monkeypatch.setattr(memory_monitor, "_read_cgroup_v2_memory", lambda: v2)
    monkeypatch.setattr(
        memory_monitor,
        "_read_cgroup_v1_memory",
        lambda: pytest.fail("v1 must not be read when v2 is valid"),
    )

    assert memory_monitor._cgroup_memory_snapshot() is v2


@pytest.mark.parametrize(
    ("host_available", "cgroup_available", "expected"),
    [(10.0, 4.0, 4.0), (3.0, 8.0, 3.0)],
)
def test_effective_available_memory_uses_smaller_value(
    monkeypatch,
    host_available,
    cgroup_available,
    expected,
):
    monkeypatch.setattr(
        memory_monitor,
        "_system_memory_snapshot",
        lambda: {"ram_available_gb": host_available},
    )
    monkeypatch.setattr(
        memory_monitor,
        "_cgroup_memory_snapshot",
        lambda: {
            "cgroup_memory_limit_gb": 12.0,
            "cgroup_memory_current_gb": 12.0 - cgroup_available,
            "cgroup_memory_available_gb": cgroup_available,
        },
    )
    monkeypatch.setattr(memory_monitor, "_nvidia_smi_memory_snapshot", lambda: {})

    snapshot = memory_monitor.collect_memory_snapshot(torch_module=object())

    assert snapshot["effective_available_ram_gb"] == expected


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


def test_memory_guard_prefers_effective_available_and_reports_cgroup_detail():
    measured = {
        "ram_available_gb": 20.0,
        "cgroup_memory_limit_gb": 12.0,
        "cgroup_memory_current_gb": 7.0,
        "cgroup_memory_available_gb": 5.0,
        "effective_available_ram_gb": 5.0,
        "process_rss_gb": 2.0,
        "swap_used_gb": 1.0,
    }

    with pytest.raises(AppException) as exc_info:
        memory_monitor.ensure_model_load_memory(
            model_name="sd15_controlnet_tile",
            min_available_ram_gb=6.0,
            load_stage="before_base_pipeline_load",
            snapshot=measured,
        )

    assert exc_info.value.detail == {
        "model_name": "sd15_controlnet_tile",
        "load_stage": "before_base_pipeline_load",
        "ram_available_gb": 20.0,
        "cgroup_memory_limit_gb": 12.0,
        "cgroup_memory_current_gb": 7.0,
        "cgroup_memory_available_gb": 5.0,
        "effective_available_ram_gb": 5.0,
        "required_ram_gb": 6.0,
        "process_rss_gb": 2.0,
        "swap_used_gb": 1.0,
    }


def test_memory_guard_falls_back_to_host_available():
    measured = _snapshot(6.0)
    measured["effective_available_ram_gb"] = None

    assert memory_monitor.ensure_model_load_memory(
        model_name="fallback",
        min_available_ram_gb=6.0,
        snapshot=measured,
    ) is measured


def test_memory_guard_passes_when_memory_cannot_be_measured():
    measured = {
        "ram_available_gb": None,
        "effective_available_ram_gb": None,
    }

    assert memory_monitor.ensure_model_load_memory(
        model_name="unknown",
        min_available_ram_gb=6.0,
        snapshot=measured,
    ) is measured


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
