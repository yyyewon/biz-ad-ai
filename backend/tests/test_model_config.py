from pathlib import Path

import pytest

from app.core import model_config
from app.core.exceptions import AppException


def test_resolve_model_config_path():
    path = model_config.resolve_model_config_path()

    assert isinstance(path, Path)
    assert path.name == "model.yaml"
    assert path.exists()


def test_load_model_config():
    config = model_config.reload_model_config()

    assert isinstance(config, dict)
    assert config["active_profile"] in config["profiles"]


def test_get_active_profile():
    config = model_config.reload_model_config()

    active_profile_name = model_config.get_active_profile_name()
    active_profile = model_config.get_active_profile()

    assert active_profile_name == config["active_profile"]
    assert isinstance(active_profile, dict)
    assert "text_generation_provider" in active_profile
    assert "image_generation_provider" in active_profile


def test_get_provider_name():
    model_config.reload_model_config()

    text_provider = model_config.get_provider_name("text_generation")
    image_provider = model_config.get_provider_name("image_generation")

    assert text_provider in {"openai", "hf"}
    assert image_provider in {"openai", "hf"}


def test_get_text_generation_settings():
    model_config.reload_model_config()

    settings = model_config.get_text_generation_settings()

    assert settings["role"] == "text_generation"
    assert settings["provider"] in {"openai", "hf"}
    assert settings["model_name"]
    assert isinstance(settings["settings"], dict)


def test_get_image_generation_settings():
    model_config.reload_model_config()

    settings = model_config.get_image_generation_settings()

    assert settings["role"] == "image_generation"
    assert settings["provider"] in {"openai", "hf"}
    assert settings["model_name"]
    assert isinstance(settings["settings"], dict)


def test_get_image_preprocess_settings():
    model_config.reload_model_config()

    settings = model_config.get_image_preprocess_settings()

    assert settings["provider"] == "pillow"
    assert settings["target_width"] > 0
    assert settings["target_height"] > 0


def test_get_output_image_settings():
    model_config.reload_model_config()

    settings = model_config.get_output_image_settings()

    assert settings["width"] > 0
    assert settings["height"] > 0
    assert settings["default_count"] > 0
    assert settings["max_count"] >= settings["default_count"]


def test_get_performance_logging_settings():
    model_config.reload_model_config()

    settings = model_config.get_performance_logging_settings()

    assert "enabled" in settings
    assert "path" in settings


def test_model_config_path_env_override(monkeypatch, tmp_path):
    temp_config_path = tmp_path / "model.yaml"

    temp_config_path.write_text(
        """
version: 1
active_profile: all_openai
profiles:
  all_openai:
    text_generation_provider: openai
    image_generation_provider: openai
runtime:
  device: auto
  dtype: auto
  seed: null
output_image:
  width: 1080
  height: 1350
  mime_type: image/png
  default_count: 3
  max_count: 4
image_preprocess:
  provider: pillow
  target_width: 512
  target_height: 512
  output_format: png
logging:
  performance:
    enabled: true
    path: logs/performance.jsonl
    include_extra: true
openai:
  text_generation:
    default_model: gpt-4o-mini
    models:
      gpt-4o-mini:
        api_type: chat_completions
        temperature: 0.7
        max_tokens: 800
  image_generation:
    default_model: gpt-image-1-mini
    models:
      gpt-image-1-mini:
        api_type: images
        size: 1024x1536
        quality: medium
        output_format: png
hf:
  text_generation:
    default_model: qwen3_4b
    models:
      qwen3_4b:
        model_id: Qwen/Qwen3-4B-Instruct-2507
  image_generation:
    default_model: sdxl_lightning
    models:
      sdxl_lightning:
        model_id: ByteDance/SDXL-Lightning
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("MODEL_CONFIG_PATH", str(temp_config_path))

    config = model_config.reload_model_config()

    assert config["active_profile"] == "all_openai"
    assert model_config.resolve_model_config_path() == temp_config_path.resolve()

    monkeypatch.delenv("MODEL_CONFIG_PATH", raising=False)
    model_config.reload_model_config()


def test_invalid_role_raises_app_exception():
    model_config.reload_model_config()

    with pytest.raises(AppException):
        model_config.get_provider_name("unknown_role")