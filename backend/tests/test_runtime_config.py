import pytest

from app.core.config import Settings


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_model_warmup_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MODEL_WARMUP_ENABLED", raising=False)

    assert _settings().model_warmup_enabled is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "on"])
def test_model_warmup_parses_truthy_values(monkeypatch, value):
    monkeypatch.setenv("MODEL_WARMUP_ENABLED", value)

    assert _settings().model_warmup_enabled is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off"])
def test_model_warmup_parses_falsy_values(monkeypatch, value):
    monkeypatch.setenv("MODEL_WARMUP_ENABLED", value)

    assert _settings().model_warmup_enabled is False


def test_model_memory_threshold_and_cpu_offload_parse(monkeypatch):
    monkeypatch.setenv("MODEL_LOAD_MIN_AVAILABLE_RAM_GB", "7.5")
    monkeypatch.setenv("HF_IMAGE_CPU_OFFLOAD_ENABLED", "yes")

    settings = _settings()

    assert settings.model_load_min_available_ram_gb == 7.5
    assert settings.hf_image_cpu_offload_enabled is True
