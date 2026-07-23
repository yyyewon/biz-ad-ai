from app.services.providers import factory
from app.services.providers.hf_sdxl_ip_adapter_provider import (
    HFSDXLIPAdapterImageProvider,
)


def _model_settings() -> dict:
    return {
        "provider_type": "sdxl_ip_adapter",
        "base_model_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "inpaint_model_id": "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
        "width": 1024,
        "height": 1024,
        "max_native_side": 1152,
        "img2img_restyle_strength": 0.35,
        "ip_adapter": {
            "enabled": True,
            "repo_id": "h94/IP-Adapter",
            "subfolder": "sdxl_models",
            "weight_name": "ip-adapter-plus_sdxl_vit-h.safetensors",
            "image_encoder_folder": "models/image_encoder",
            "scale": 0.55,
        },
    }


def test_factory_selects_sdxl_ip_adapter_provider(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.setattr(factory, "get_provider_name", lambda _role: "hf")
    monkeypatch.setattr(
        factory,
        "get_model_settings",
        lambda **_kwargs: {
            "model_name": "sdxl_ip_adapter",
            "settings": _model_settings(),
        },
    )

    provider = factory.get_image_provider()

    assert isinstance(provider, HFSDXLIPAdapterImageProvider)


def test_strength_and_portrait_native_size_are_preserved():
    provider = HFSDXLIPAdapterImageProvider(
        model_name="sdxl_ip_adapter",
        model_settings=_model_settings(),
        hf_token="test-token",
    )

    assert provider._resolve_img2img_strength(0.42) == 0.42
    assert provider._resolve_img2img_strength(None) == 0.35
    assert provider._resolve_native_size((1024, 1536)) == (768, 1152)
