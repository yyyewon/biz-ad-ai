import asyncio

import pytest
from PIL import Image

from app.core import model_config
from app.core.exceptions import AppException
from app.services.providers.hf_image_provider import HFImageProvider
from app.utils.image_bytes import image_bytes_to_pil, pil_image_to_png_bytes


def _write_model_config(path, active_profile="hybrid_openai_text_hf_image"):
    path.write_text(
        f"""
version: 1
active_profile: {active_profile}
profiles:
  all_openai:
    text_generation_provider: openai
    image_generation_provider: openai
  hybrid_openai_text_hf_image:
    text_generation_provider: openai
    image_generation_provider: hf
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
    enabled: false
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
  image_generation:
    default_model: sd35_medium
    models:
      sd35_medium:
        model_id: stabilityai/stable-diffusion-3.5-medium
        width: 64
        height: 64
        num_inference_steps: 4
        guidance_scale: 4.5
        img2img_strength: 0.65
""",
        encoding="utf-8",
    )


def _build_provider(monkeypatch, tmp_path):
    config_path = tmp_path / "model.yaml"
    _write_model_config(config_path)

    monkeypatch.setenv("MODEL_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HF_TOKEN", "test-hf-token")
    model_config.reload_model_config()

    return HFImageProvider()


def _teardown(monkeypatch):
    monkeypatch.delenv("MODEL_CONFIG_PATH", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    model_config.reload_model_config()


def test_missing_hf_token_raises_app_exception(monkeypatch, tmp_path):
    config_path = tmp_path / "model.yaml"
    _write_model_config(config_path)

    monkeypatch.setenv("MODEL_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HF_TOKEN", "")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf-cache"))
    model_config.reload_model_config()

    with pytest.raises(AppException) as exc_info:
        HFImageProvider()

    assert exc_info.value.code == "HF_TOKEN_MISSING"

    _teardown(monkeypatch)


def test_generate_backgrounds_returns_png_bytes(monkeypatch, tmp_path):
    provider = _build_provider(monkeypatch, tmp_path)

    fake_images = [Image.new("RGB", (64, 64), "green") for _ in range(2)]

    class FakeResult:
        images = fake_images

    class FakePipe:
        def __call__(self, **kwargs):
            assert kwargs["num_images_per_prompt"] == 2
            return FakeResult()

    monkeypatch.setattr(provider, "_load_text2img_pipeline", lambda: FakePipe())

    result = asyncio.run(
        provider.generate_backgrounds(prompt="테스트 프롬프트", num_images=2)
    )

    assert len(result) == 2
    for image_bytes in result:
        assert image_bytes_to_pil(image_bytes).size == (64, 64)

    _teardown(monkeypatch)


def test_generate_with_mask_preserves_subject_pixels(monkeypatch, tmp_path):
    provider = _build_provider(monkeypatch, tmp_path)

    size = (64, 64)
    original = Image.new("RGB", size, "white")
    generated = Image.new("RGB", size, "blue")

    class FakeResult:
        images = [generated]

    class FakePipe:
        def __call__(self, **kwargs):
            return FakeResult()

    monkeypatch.setattr(provider, "_load_text2img_pipeline", lambda: FakePipe())
    provider._seam_blend_enabled = False
    provider._color_harmonize_strength = 0.0
    provider._drop_shadow_opacity = 0.0
    provider._composite_feather_px = 0

    # 왼쪽 절반: alpha=255(피사체 보존), 오른쪽 절반: alpha=0(배경 교체)
    mask = Image.new("RGBA", size, (0, 0, 0, 0))
    for x in range(size[0] // 2):
        for y in range(size[1]):
            mask.putpixel((x, y), (0, 0, 0, 255))

    result = asyncio.run(
        provider.generate(
            input_image_bytes=pil_image_to_png_bytes(original),
            prompt="테스트",
            num_images=1,
            mask_image_bytes=pil_image_to_png_bytes(mask),
            render_mode="background_swap",
        )
    )

    output_image = image_bytes_to_pil(result[0]).convert("RGB")

    # 배경(상단)은 생성된 backdrop, 하단 히어로 영역은 원본 피사체가 합성된다.
    assert output_image.getpixel((60, 8)) == (0, 0, 255)
    assert output_image.getpixel((30, 58)) == (255, 255, 255)

    _teardown(monkeypatch)