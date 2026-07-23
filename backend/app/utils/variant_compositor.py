"""Deterministic SDXL canvases for studio, poster, and Instagram variants."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageFilter, ImageOps, ImageStat

from app.schemas.food_type import FoodType
from app.schemas.image_ad import ImageVariantType
from app.services.providers.base import ImageRenderMode
from app.utils.food_subject import PreparedFoodSubject
from app.utils.image_bytes import pil_image_to_png_bytes


HF_VARIANT_NATIVE_SIZES: dict[ImageVariantType, tuple[int, int]] = {
    "studio": (1024, 1024),
    "poster": (768, 1152),
    "instagram_feed": (768, 1152),
}

_SUBJECT_HEIGHT_RATIOS: dict[ImageVariantType, float] = {
    "studio": 0.56,
    "poster": 0.38,
    "instagram_feed": 1.0,
}
_BOTTOM_MARGIN_RATIOS: dict[ImageVariantType, float] = {
    "studio": 0.10,
    "poster": 0.08,
    "instagram_feed": 0.0,
}
_IP_ADAPTER_SCALES: dict[ImageVariantType, float] = {
    "studio": 0.60,
    "poster": 0.65,
    "instagram_feed": 0.30,
}
_IMG2IMG_STRENGTHS: dict[ImageVariantType, float] = {
    "studio": 0.42,
    "poster": 0.42,
    "instagram_feed": 0.30,
}


@dataclass(frozen=True)
class PreparedVariantInput:
    variant: ImageVariantType
    init_image_bytes: bytes
    mask_image_bytes: bytes | None
    reference_image_bytes: bytes | None
    subject_layer_bytes: bytes | None
    render_mode: ImageRenderMode
    img2img_strength: float
    inpaint_strength: float
    ip_adapter_scale: float
    native_size: tuple[int, int]
    num_inference_steps: int
    guidance_scale: float
    text_safe_zone_ratio: float | None
    segmentation_valid: bool
    segmentation_fallback_reason: str | None
    subject_bbox: tuple[int, int, int, int] | None
    subject_area_ratio: float
    background_fallback_bytes: bytes | None


@dataclass(frozen=True)
class PosterBackgroundQuality:
    accepted: bool
    edge_mean: float
    luminance_variance: float


def prepare_variant_input(
    subject: PreparedFoodSubject,
    variant: ImageVariantType,
    *,
    food_type: FoodType,
    settings: dict[str, object] | None = None,
) -> PreparedVariantInput:
    settings = settings or {}
    native_size = _resolve_native_size(settings.get("native_size"), variant)
    subject_height_ratio = float(
        settings.get("subject_height_ratio", _SUBJECT_HEIGHT_RATIOS[variant])
    )
    bottom_margin_ratio = float(
        settings.get("subject_bottom_margin_ratio", _BOTTOM_MARGIN_RATIOS[variant])
    )
    img2img_strength = float(
        settings.get("img2img_strength", _IMG2IMG_STRENGTHS[variant])
    )
    inpaint_strength = float(settings.get("inpaint_strength", 0.95))
    ip_adapter_scale = float(
        settings.get("ip_adapter_scale", _IP_ADAPTER_SCALES[variant])
    )
    default_steps = 24 if variant == "instagram_feed" else (26 if variant == "studio" else 28)
    default_guidance = 5.0 if variant == "instagram_feed" else (5.5 if variant == "studio" else 6.0)
    num_inference_steps = int(settings.get("num_inference_steps", default_steps))
    guidance_scale = float(settings.get("guidance_scale", default_guidance))
    text_safe_zone_ratio = (
        float(settings.get("text_safe_zone_ratio", 0.42))
        if variant == "poster"
        else None
    )
    reference_bytes = pil_image_to_png_bytes(subject.reference_rgb)

    if variant == "instagram_feed":
        init_image = _aspect_safe_fit(
            subject.source_rgb,
            native_size,
            subject.subject_bbox,
        )
        return PreparedVariantInput(
            variant=variant,
            init_image_bytes=pil_image_to_png_bytes(init_image),
            mask_image_bytes=None,
            reference_image_bytes=reference_bytes,
            subject_layer_bytes=None,
            render_mode="photo_restyle",
            img2img_strength=img2img_strength,
            inpaint_strength=inpaint_strength,
            ip_adapter_scale=ip_adapter_scale,
            native_size=native_size,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            text_safe_zone_ratio=None,
            segmentation_valid=subject.segmentation_valid,
            segmentation_fallback_reason=subject.fallback_reason,
            subject_bbox=subject.subject_bbox,
            subject_area_ratio=subject.subject_area_ratio,
            background_fallback_bytes=None,
        )

    if not subject.segmentation_valid or subject.subject_rgba is None or subject.subject_bbox is None:
        fallback = _aspect_safe_fit(subject.source_rgb, native_size, None)
        fallback_bytes = pil_image_to_png_bytes(fallback)
        return PreparedVariantInput(
            variant=variant,
            init_image_bytes=fallback_bytes,
            mask_image_bytes=None,
            reference_image_bytes=reference_bytes,
            subject_layer_bytes=None,
            render_mode="photo_restyle",
            img2img_strength=img2img_strength,
            inpaint_strength=inpaint_strength,
            ip_adapter_scale=ip_adapter_scale,
            native_size=native_size,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            text_safe_zone_ratio=text_safe_zone_ratio,
            segmentation_valid=False,
            segmentation_fallback_reason=subject.fallback_reason,
            subject_bbox=None,
            subject_area_ratio=subject.subject_area_ratio,
            background_fallback_bytes=fallback_bytes,
        )

    background = _build_background(native_size, food_type=food_type, variant=variant)
    subject_layer, placed_bbox = _place_subject(
        subject.subject_rgba,
        subject.subject_bbox,
        native_size,
        height_ratio=subject_height_ratio,
        bottom_margin_ratio=bottom_margin_ratio,
    )
    init_image = _composite_subject(background, subject_layer, add_shadow=True)
    mask = ImageOps.invert(subject_layer.getchannel("A"))
    init_bytes = pil_image_to_png_bytes(init_image)

    return PreparedVariantInput(
        variant=variant,
        init_image_bytes=init_bytes,
        mask_image_bytes=pil_image_to_png_bytes(mask),
        reference_image_bytes=reference_bytes,
        subject_layer_bytes=pil_image_to_png_bytes(subject_layer),
        render_mode="background_swap",
        img2img_strength=img2img_strength,
        inpaint_strength=inpaint_strength,
        ip_adapter_scale=ip_adapter_scale,
        native_size=native_size,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        text_safe_zone_ratio=text_safe_zone_ratio,
        segmentation_valid=True,
        segmentation_fallback_reason=None,
        subject_bbox=placed_bbox,
        subject_area_ratio=subject.subject_area_ratio,
        background_fallback_bytes=init_bytes,
    )


def _resolve_native_size(
    raw: object,
    variant: ImageVariantType,
) -> tuple[int, int]:
    if isinstance(raw, str) and "x" in raw.lower():
        width, height = raw.lower().split("x", maxsplit=1)
        return int(width), int(height)
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return int(raw[0]), int(raw[1])
    return HF_VARIANT_NATIVE_SIZES[variant]


def recomposite_subject(generated: Image.Image, subject_layer: Image.Image) -> Image.Image:
    layer = subject_layer.convert("RGBA")
    if layer.size != generated.size:
        layer = layer.resize(generated.size, Image.Resampling.LANCZOS)
    return _composite_subject(generated.convert("RGB"), layer, add_shadow=False)


def evaluate_poster_background(image: Image.Image) -> PosterBackgroundQuality:
    rgb = image.convert("RGB")
    top = rgb.crop((0, 0, rgb.width, max(1, int(rgb.height * 0.40))))
    grayscale = ImageOps.grayscale(top)
    edge_mean = float(ImageStat.Stat(grayscale.filter(ImageFilter.FIND_EDGES)).mean[0])
    luminance_variance = float(ImageStat.Stat(grayscale).var[0])
    accepted = edge_mean <= 34.0 and luminance_variance <= 3600.0
    return PosterBackgroundQuality(
        accepted=accepted,
        edge_mean=edge_mean,
        luminance_variance=luminance_variance,
    )


def _aspect_safe_fit(
    image: Image.Image,
    size: tuple[int, int],
    bbox: tuple[int, int, int, int] | None,
) -> Image.Image:
    centering = (0.5, 0.5)
    if bbox is not None:
        center_x = ((bbox[0] + bbox[2]) / 2) / image.width
        center_y = ((bbox[1] + bbox[3]) / 2) / image.height
        centering = (
            max(0.28, min(0.72, center_x)),
            max(0.28, min(0.72, center_y)),
        )
    return ImageOps.fit(
        image.convert("RGB"),
        size,
        method=Image.Resampling.LANCZOS,
        centering=centering,
    )


def _build_background(
    size: tuple[int, int],
    *,
    food_type: FoodType,
    variant: ImageVariantType,
) -> Image.Image:
    palettes: dict[FoodType, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
        "bread_dessert": ((246, 232, 208), (198, 158, 117)),
        "fried": ((248, 222, 158), (210, 139, 62)),
        "soup_stew": ((244, 226, 202), (193, 112, 78)),
        "coffee_drink": ((239, 235, 216), (159, 172, 139)),
        "grilled_bbq": ((232, 207, 173), (132, 83, 58)),
        "rice_dish": ((239, 225, 193), (183, 139, 86)),
        "burger_sandwich": ((243, 220, 177), (181, 118, 67)),
    }
    top, bottom = palettes[food_type]
    if variant == "studio":
        top = tuple(min(250, int(channel * 0.35 + 235 * 0.65)) for channel in top)
        bottom = tuple(min(242, int(channel * 0.30 + 218 * 0.70)) for channel in bottom)
    strip = Image.new("RGB", (1, size[1]))
    pixels = strip.load()
    for y in range(size[1]):
        ratio = y / max(1, size[1] - 1)
        pixels[0, y] = tuple(
            round(top[index] * (1.0 - ratio) + bottom[index] * ratio)
            for index in range(3)
        )
    return strip.resize(size, Image.Resampling.BILINEAR)


def _place_subject(
    subject_rgba: Image.Image,
    bbox: tuple[int, int, int, int],
    size: tuple[int, int],
    *,
    height_ratio: float,
    bottom_margin_ratio: float,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    crop = subject_rgba.crop(bbox)
    target_h = int(size[1] * height_ratio)
    target_w = int(size[0] * 0.88)
    scale = min(target_w / crop.width, target_h / crop.height)
    resized = crop.resize(
        (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
        Image.Resampling.LANCZOS,
    )
    x = (size[0] - resized.width) // 2
    y = size[1] - int(size[1] * bottom_margin_ratio) - resized.height
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.alpha_composite(resized, (x, y))
    return layer, (x, y, x + resized.width, y + resized.height)


def _composite_subject(
    background: Image.Image,
    subject_layer: Image.Image,
    *,
    add_shadow: bool,
) -> Image.Image:
    canvas = background.convert("RGBA")
    if add_shadow:
        alpha = subject_layer.getchannel("A")
        shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(radius=max(4, background.width // 90)))
        shadow_alpha = shadow_alpha.point(lambda value: int(value * 0.20))
        shadow = Image.new("RGBA", background.size, (45, 31, 20, 0))
        shadow.putalpha(shadow_alpha)
        offset = max(3, background.height // 180)
        shifted = Image.new("RGBA", background.size, (0, 0, 0, 0))
        shifted.alpha_composite(shadow, (0, offset))
        canvas.alpha_composite(shifted)
    canvas.alpha_composite(subject_layer)
    return canvas.convert("RGB")
