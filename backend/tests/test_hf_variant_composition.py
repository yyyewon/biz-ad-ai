import asyncio

from PIL import Image, ImageDraw

from app.schemas.image_ad import ImageAdRequest
from app.services.pipelines import image_pipeline
from app.utils.food_subject import PreparedFoodSubject
from app.utils.image_bytes import pil_image_to_png_bytes
from app.utils.variant_compositor import prepare_variant_input


def _prepared_subject() -> PreparedFoodSubject:
    source = Image.new("RGB", (400, 320), (52, 48, 44))
    rgba = source.convert("RGBA")
    alpha = Image.new("L", source.size, 0)
    draw = ImageDraw.Draw(alpha)
    draw.ellipse((50, 105, 350, 290), fill=255)
    draw.polygon(((115, 200), (205, 115), (315, 220)), fill=255)
    rgba.putalpha(alpha)
    reference = Image.new("RGB", (512, 512), (218, 216, 212))
    reference.paste(source.crop((50, 105, 350, 290)).resize((410, 250)), (51, 131))
    return PreparedFoodSubject(
        source_rgb=source,
        subject_rgba=rgba,
        subject_alpha=alpha,
        subject_bbox=(50, 105, 350, 290),
        reference_rgb=reference,
        segmentation_valid=True,
        fallback_reason=None,
        subject_area_ratio=0.31,
    )


def test_variant_preparation_selects_inpaint_and_separate_reference():
    subject = _prepared_subject()
    studio = prepare_variant_input(subject, "studio", food_type="bread_dessert")
    poster = prepare_variant_input(subject, "poster", food_type="bread_dessert")
    instagram = prepare_variant_input(
        subject,
        "instagram_feed",
        food_type="bread_dessert",
    )

    assert studio.render_mode == "background_swap"
    assert poster.render_mode == "background_swap"
    assert studio.mask_image_bytes and poster.mask_image_bytes
    assert instagram.render_mode == "photo_restyle"
    assert instagram.mask_image_bytes is None
    assert studio.reference_image_bytes != studio.init_image_bytes
    assert poster.reference_image_bytes != poster.init_image_bytes


def test_hf_pipeline_groups_inpaint_before_img2img(monkeypatch):
    calls: list[dict[str, object]] = []

    class FakeHFProvider:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            return [kwargs["input_image_bytes"]]

    monkeypatch.setattr(image_pipeline, "get_image_provider", lambda: FakeHFProvider())
    monkeypatch.setattr(image_pipeline, "get_provider_name", lambda _role: "hf")
    monkeypatch.setattr(
        image_pipeline,
        "get_model_settings",
        lambda *args, **kwargs: {
            "provider": "hf",
            "model_name": "sdxl_ip_adapter",
            "settings": {"variants": {}},
        },
    )
    monkeypatch.setattr(
        image_pipeline,
        "get_variant_image_size",
        lambda variant: "1024x1024" if variant == "studio" else "1024x1536",
    )
    monkeypatch.setattr(image_pipeline, "prepare_food_subject", lambda _source: _prepared_subject())
    monkeypatch.setattr(
        image_pipeline,
        "variant_uses_pil_text_overlay",
        lambda _food_type, _variant: False,
    )
    monkeypatch.setattr(image_pipeline, "record_registry_metric", lambda *args, **kwargs: None)

    payload = ImageAdRequest(
        menu_name="치즈케이크",
        food_type="bread_dessert",
        num_images=3,
    )
    result = asyncio.run(
        image_pipeline.generate_image_ads(
            payload,
            pil_image_to_png_bytes(_prepared_subject().source_rgb),
            seed=42,
        )
    )

    assert result.applied_variants == ["studio", "poster", "instagram_feed"]
    assert [call["render_mode"] for call in calls] == [
        "background_swap",
        "background_swap",
        "photo_restyle",
    ]
    assert calls[0]["mask_image_bytes"] is not None
    assert calls[1]["mask_image_bytes"] is not None
    assert calls[2]["mask_image_bytes"] is None
    assert calls[0]["input_image_bytes"] != calls[0]["reference_image_bytes"]
