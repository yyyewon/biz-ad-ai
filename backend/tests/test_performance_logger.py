import json
from pathlib import Path

import pytest

from app.core import model_config
from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.utils.performance_logger import (
    measure_stage,
    record_performance_metric,
)


def _write_temp_model_config(path: Path, performance_log_path: Path) -> None:
    path.write_text(
        f"""
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
  provider: rembg
  target_width: 512
  target_height: 512
  output_format: png
logging:
  performance:
    enabled: true
    path: {json.dumps(str(performance_log_path))}
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


def test_record_performance_metric_writes_jsonl(monkeypatch, tmp_path):
    config_path = tmp_path / "model.yaml"
    performance_log_path = tmp_path / "performance.jsonl"

    _write_temp_model_config(config_path, performance_log_path)

    monkeypatch.setenv("MODEL_CONFIG_PATH", str(config_path))
    model_config.reload_model_config()

    metric = record_performance_metric(
        pipeline="ad_generate",
        stage="text_generation",
        request_id="test-request-id",
        provider="openai",
        model="gpt-4o-mini",
        elapsed_ms=123.4567,
        success=True,
        extra={"test": True},
    )

    assert metric["event"] == "perf_metric"
    assert metric["pipeline"] == "ad_generate"
    assert metric["stage"] == "text_generation"
    assert metric["provider"] == "openai"
    assert metric["model"] == "gpt-4o-mini"
    assert metric["elapsed_ms"] == 123.457
    assert metric["success"] is True

    assert performance_log_path.exists()

    lines = performance_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    saved = json.loads(lines[0])
    assert saved["event"] == "perf_metric"
    assert saved["request_id"] == "test-request-id"
    assert saved["profile"] == "all_openai"
    assert saved["extra"] == {"test": True}

    monkeypatch.delenv("MODEL_CONFIG_PATH", raising=False)
    model_config.reload_model_config()


def test_measure_stage_success_writes_success_metric(monkeypatch, tmp_path):
    config_path = tmp_path / "model.yaml"
    performance_log_path = tmp_path / "performance.jsonl"

    _write_temp_model_config(config_path, performance_log_path)

    monkeypatch.setenv("MODEL_CONFIG_PATH", str(config_path))
    model_config.reload_model_config()

    with measure_stage(
        pipeline="ad_generate",
        stage="image_generation",
        request_id="request-success",
        provider="openai",
        model="gpt-image-1-mini",
    ):
        value = 1 + 1
        assert value == 2

    lines = performance_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    saved = json.loads(lines[0])
    assert saved["stage"] == "image_generation"
    assert saved["success"] is True
    assert saved["elapsed_ms"] >= 0

    monkeypatch.delenv("MODEL_CONFIG_PATH", raising=False)
    model_config.reload_model_config()


def test_measure_stage_app_exception_writes_failure_metric(monkeypatch, tmp_path):
    config_path = tmp_path / "model.yaml"
    performance_log_path = tmp_path / "performance.jsonl"

    _write_temp_model_config(config_path, performance_log_path)

    monkeypatch.setenv("MODEL_CONFIG_PATH", str(config_path))
    model_config.reload_model_config()

    with pytest.raises(AppException):
        with measure_stage(
            pipeline="ad_generate",
            stage="text_generation",
            request_id="request-failure",
            provider="openai",
            model="gpt-4o-mini",
        ):
            raise AppException(errors.OPENAI_TEXT_GENERATION_FAILED)

    lines = performance_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    saved = json.loads(lines[0])
    assert saved["stage"] == "text_generation"
    assert saved["success"] is False
    assert saved["error_code"] == "OPENAI_TEXT_GENERATION_FAILED"
    assert saved["error_type"] == "AppException"

    monkeypatch.delenv("MODEL_CONFIG_PATH", raising=False)
    model_config.reload_model_config()


def test_measure_stage_unhandled_exception_writes_failure_metric(monkeypatch, tmp_path):
    config_path = tmp_path / "model.yaml"
    performance_log_path = tmp_path / "performance.jsonl"

    _write_temp_model_config(config_path, performance_log_path)

    monkeypatch.setenv("MODEL_CONFIG_PATH", str(config_path))
    model_config.reload_model_config()

    with pytest.raises(RuntimeError):
        with measure_stage(
            pipeline="ad_generate",
            stage="image_generation",
            request_id="request-runtime-error",
            provider="hf",
            model="sdxl_lightning",
        ):
            raise RuntimeError("boom")

    lines = performance_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    saved = json.loads(lines[0])
    assert saved["stage"] == "image_generation"
    assert saved["success"] is False
    assert saved["error_code"] == "UNHANDLED_EXCEPTION"
    assert saved["error_type"] == "RuntimeError"

    monkeypatch.delenv("MODEL_CONFIG_PATH", raising=False)
    model_config.reload_model_config()
