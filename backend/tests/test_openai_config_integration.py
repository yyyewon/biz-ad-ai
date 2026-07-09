from pathlib import Path
import asyncio

import pytest

from app.core import model_config
from app.core.exceptions import AppException
from app.services.pipelines import text_pipeline
from app.services.providers.factory import get_image_provider, get_text_provider
from app.services.providers.openai_image_provider import OpenAIImageProvider
from app.services.providers.openai_text_provider import OpenAITextProvider
from app.services.providers.hf_image_provider import HFImageProvider


def _write_model_config(path: Path, active_profile: str = "all_openai") -> None:
    path.write_text(
        f"""
version: 1
active_profile: {active_profile}
profiles:
  all_openai:
    text_generation_provider: openai
    image_generation_provider: openai
  all_hf:
    text_generation_provider: hf
    image_generation_provider: hf
  hybrid_openai_text_hf_image:
    text_generation_provider: openai
    image_generation_provider: hf
  hybrid_hf_text_openai_image:
    text_generation_provider: hf
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
    path: logs/performance.jsonl
    include_extra: true
openai:
  api_key_env: OPENAI_API_KEY
  text_generation:
    default_model: gpt-4o-mini
    models:
      gpt-4o-mini:
        api_type: chat_completions
        temperature: 0.7
        max_tokens: 800
      gpt-5-mini:
        api_type: responses
        reasoning_effort: low
        verbosity: medium
        max_output_tokens: 800
  image_generation:
    default_model: gpt-image-1-mini
    models:
      gpt-image-1-mini:
        api_type: images
        size: 1024x1536
        quality: medium
        output_format: png
hf:
  token_env: HF_TOKEN
  text_generation:
    default_model: qwen3_4b
    models:
      qwen3_4b:
        model_id: Qwen/Qwen3-4B-Instruct-2507
        task_type: text-generation
  image_generation:
    default_model: sdxl_lightning
    models:
      sdxl_lightning:
        model_id: ByteDance/SDXL-Lightning
        task_type: text-to-image
""",
        encoding="utf-8",
    )


def test_get_text_provider_uses_openai_config(monkeypatch, tmp_path):
    config_path = tmp_path / "model.yaml"
    _write_model_config(config_path, active_profile="all_openai")

    monkeypatch.setenv("MODEL_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")

    model_config.reload_model_config()

    provider = get_text_provider()

    assert isinstance(provider, OpenAITextProvider)
    assert provider.model_name == "gpt-4o-mini"
    assert provider.model_settings["api_type"] == "chat_completions"

    monkeypatch.delenv("MODEL_CONFIG_PATH", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    model_config.reload_model_config()


def test_get_image_provider_uses_openai_config(monkeypatch, tmp_path):
    config_path = tmp_path / "model.yaml"
    _write_model_config(config_path, active_profile="all_openai")

    monkeypatch.setenv("MODEL_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")

    model_config.reload_model_config()

    provider = get_image_provider()

    assert isinstance(provider, OpenAIImageProvider)
    assert provider.model_name == "gpt-image-1-mini"
    assert provider.size == "1024x1536"
    assert provider.output_format == "png"

    monkeypatch.delenv("MODEL_CONFIG_PATH", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    model_config.reload_model_config()


def test_hf_text_provider_is_not_available_yet(monkeypatch, tmp_path):
    config_path = tmp_path / "model.yaml"
    _write_model_config(config_path, active_profile="all_hf")

    monkeypatch.setenv("MODEL_CONFIG_PATH", str(config_path))
    model_config.reload_model_config()

    with pytest.raises(AppException) as exc_info:
        get_text_provider()

    assert exc_info.value.code == "HF_PROVIDER_NOT_AVAILABLE"

    monkeypatch.delenv("MODEL_CONFIG_PATH", raising=False)
    model_config.reload_model_config()


def test_get_hf_image_provider_requires_token(monkeypatch, tmp_path):
    config_path = tmp_path / "model.yaml"
    _write_model_config(config_path, active_profile="hybrid_openai_text_hf_image")

    monkeypatch.setenv("MODEL_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("HF_TOKEN", raising=False)
    model_config.reload_model_config()

    with pytest.raises(AppException) as exc_info:
        get_image_provider()

    assert exc_info.value.code == "HF_TOKEN_MISSING"

    monkeypatch.delenv("MODEL_CONFIG_PATH", raising=False)
    model_config.reload_model_config()


def test_get_hf_image_provider_with_token_succeeds(monkeypatch, tmp_path):
    config_path = tmp_path / "model.yaml"
    _write_model_config(config_path, active_profile="hybrid_openai_text_hf_image")

    monkeypatch.setenv("MODEL_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HF_TOKEN", "test-hf-token")
    model_config.reload_model_config()

    provider = get_image_provider()

    assert isinstance(provider, HFImageProvider)
    assert provider.model_id

    monkeypatch.delenv("MODEL_CONFIG_PATH", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    model_config.reload_model_config()


def test_text_pipeline_uses_text_provider(monkeypatch):
    class FakeTextProvider:
        async def generate_text(self, prompt: str, system_instruction: str) -> str:
            assert "테스트가게" in prompt
            assert "김밥" in prompt
            assert "광고 카피라이터" in system_instruction
            return "테스트 광고 문구입니다. #김밥 #분식 #맛집 #점심 #추천"

    monkeypatch.setattr(
        text_pipeline,
        "get_text_provider",
        lambda: FakeTextProvider(),
    )

    result = asyncio.run(
        text_pipeline.run_text_pipeline(
        store_name="테스트가게",
        menu_name="김밥",
        purpose="신메뉴 홍보",
        request_note="가성비를 강조",
        moods=["fresh"],
        tone="친근한",
      )
    )

    assert "테스트 광고 문구입니다." in result
