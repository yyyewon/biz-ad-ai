from types import SimpleNamespace

import pytest

from app.core.exceptions import AppException
from app.services.providers import hf_sd15_controlnet_tile_provider as provider_module


class _FakeCuda:
    @staticmethod
    def is_available():
        return False


class _FakeTorch:
    float16 = object()
    cuda = _FakeCuda()


class _FakeControlNetLoader:
    calls: list[dict] = []

    @classmethod
    def from_pretrained(cls, *_args, **kwargs):
        cls.calls.append(kwargs)
        return object()


class _FakePipe:
    def __init__(self):
        self.scheduler = SimpleNamespace(config={"name": "scheduler"})
        self.to_calls: list[str] = []
        self.cpu_offload_calls = 0

    def to(self, device):
        self.to_calls.append(device)
        return self

    def enable_model_cpu_offload(self):
        self.cpu_offload_calls += 1


class _FakePipelineLoader:
    calls: list[dict] = []
    pipe: _FakePipe | None = None

    @classmethod
    def from_pretrained(cls, **kwargs):
        cls.calls.append(kwargs)
        cls.pipe = _FakePipe()
        return cls.pipe


class _FakeScheduler:
    @staticmethod
    def from_config(config):
        return SimpleNamespace(config=config)


def _provider(*, cpu_offload: bool = False):
    provider = provider_module.HFSD15ControlNetTileImageProvider.__new__(
        provider_module.HFSD15ControlNetTileImageProvider
    )
    provider._model_key = "sd15_controlnet_tile"
    provider._base_model_id = "test/base"
    provider._controlnet_model_id = "test/controlnet"
    provider._hf_token = "test-token"
    provider._use_xformers = False
    provider._enable_vae_slicing = False
    provider._cpu_offload_enabled = cpu_offload
    provider._min_available_ram_gb = 6.0
    provider._ensure_dependencies_available = lambda: None
    provider._resolve_torch_dtype = lambda: _FakeTorch.float16
    provider._resolve_device = lambda: "cuda"
    return provider


@pytest.fixture(autouse=True)
def _reset_pipeline_state(monkeypatch):
    provider_module._SD15_PIPELINE_CACHE.clear()
    _FakeControlNetLoader.calls.clear()
    _FakePipelineLoader.calls.clear()
    _FakePipelineLoader.pipe = None
    monkeypatch.setattr(provider_module, "torch", _FakeTorch())
    monkeypatch.setattr(provider_module, "ControlNetModel", _FakeControlNetLoader)
    monkeypatch.setattr(
        provider_module,
        "StableDiffusionControlNetPipeline",
        _FakePipelineLoader,
    )
    monkeypatch.setattr(provider_module, "DDIMScheduler", _FakeScheduler)
    monkeypatch.setattr(provider_module, "record_performance_metric", lambda **_kwargs: None)
    monkeypatch.setattr(
        provider_module,
        "log_model_memory_snapshot",
        lambda *_args, **_kwargs: {
            "ram_available_gb": 8.0,
            "process_rss_gb": 1.0,
            "swap_used_gb": 0.0,
        },
    )
    yield
    provider_module._SD15_PIPELINE_CACHE.clear()


def test_pipeline_load_uses_low_cpu_memory_and_reuses_cache():
    provider = _provider(cpu_offload=False)

    first_pipe, first_meta = provider._load_pipeline()
    second_pipe, second_meta = provider._load_pipeline()

    assert _FakeControlNetLoader.calls == [
        {
            "torch_dtype": _FakeTorch.float16,
            "use_safetensors": False,
            "token": "test-token",
            "low_cpu_mem_usage": True,
        }
    ]
    assert _FakePipelineLoader.calls[0]["low_cpu_mem_usage"] is True
    assert first_pipe.to_calls == ["cuda"]
    assert first_pipe.cpu_offload_calls == 0
    assert second_pipe is first_pipe
    assert second_meta is first_meta
    assert len(_FakePipelineLoader.calls) == 1


def test_pipeline_load_uses_cpu_offload_instead_of_to_cuda():
    provider = _provider(cpu_offload=True)

    pipe, meta = provider._load_pipeline()

    assert pipe.cpu_offload_calls == 1
    assert pipe.to_calls == []
    assert meta["cpu_offload_enabled"] is True


def test_memory_guard_runs_before_model_loader(monkeypatch):
    provider = _provider()
    monkeypatch.setattr(
        provider_module,
        "log_model_memory_snapshot",
        lambda *_args, **_kwargs: {
            "ram_available_gb": 5.0,
            "process_rss_gb": 1.5,
            "swap_used_gb": 0.25,
        },
    )

    with pytest.raises(AppException) as exc_info:
        provider._load_pipeline()

    assert exc_info.value.code == "MODEL_LOAD_INSUFFICIENT_SYSTEM_MEMORY"
    assert _FakeControlNetLoader.calls == []
    assert _FakePipelineLoader.calls == []
