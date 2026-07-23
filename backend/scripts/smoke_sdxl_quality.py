"""Real-GPU quality smoke for deterministic SDXL variant preparation."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.model_config import get_model_settings, get_variant_image_size  # noqa: E402
from app.schemas.image_ad import ImageAdRequest, ImageVariantType  # noqa: E402
from app.services.pipelines.image_variant_prompts import (  # noqa: E402
    build_hf_variant_prompts,
)
from app.services.providers.hf_sdxl_ip_adapter_provider import (  # noqa: E402
    HFSDXLIPAdapterImageProvider,
)
from app.utils.food_subject import prepare_food_subject  # noqa: E402
from app.utils.image_bytes import image_bytes_to_pil, pil_image_to_png_bytes  # noqa: E402
from app.utils.image_text_overlay import (  # noqa: E402
    apply_variant_text_overlay,
    variant_uses_pil_text_overlay,
)
from app.utils.memory_monitor import collect_memory_snapshot  # noqa: E402
from app.utils.variant_compositor import (  # noqa: E402
    evaluate_poster_background,
    prepare_variant_input,
    recomposite_subject,
)


VARIANTS: tuple[ImageVariantType, ...] = (
    "studio",
    "poster",
    "instagram_feed",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--store-name", default="새벽")
    parser.add_argument("--menu-name", default="치즈케이크")
    parser.add_argument("--headline", default="새 메뉴 나왔어요")
    parser.add_argument("--price", default="7,000원")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> list[dict[str, object]]:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this smoke test")
    if not args.input.is_file():
        raise FileNotFoundError(args.input)

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    source = ImageOps.exif_transpose(Image.open(args.input)).convert("RGB")
    source.save(output_dir / "input.png")
    subject = prepare_food_subject(source)
    if subject.subject_rgba is not None:
        subject.subject_rgba.save(output_dir / "subject_rgba.png")
    if subject.subject_alpha is not None:
        subject.subject_alpha.save(output_dir / "subject_mask.png")

    resolved = get_model_settings(role="image_generation", provider_name="hf")
    settings = resolved["settings"]
    if str(settings.get("provider_type")) != "sdxl_ip_adapter":
        raise RuntimeError("HF default model must use provider_type=sdxl_ip_adapter")
    provider = HFSDXLIPAdapterImageProvider(
        model_name=resolved["model_name"],
        model_settings=settings,
    )
    variant_settings = settings.get("variants", {})
    if not isinstance(variant_settings, dict):
        variant_settings = {}

    payload = ImageAdRequest(
        store_name=args.store_name,
        menu_name=args.menu_name,
        headline=args.headline,
        price_text=args.price,
        food_type="bread_dessert",
        num_images=3,
    )
    rows: list[dict[str, object]] = []

    for index, variant in enumerate(VARIANTS):
        prepared = prepare_variant_input(
            subject,
            variant,
            food_type="bread_dessert",
            settings=(
                variant_settings.get(variant)
                if isinstance(variant_settings.get(variant), dict)
                else None
            ),
        )
        prompt = build_hf_variant_prompts(
            payload,
            variant,
            food_type="bread_dessert",
        )
        prefix = "instagram" if variant == "instagram_feed" else variant
        (output_dir / f"{prefix}_init.png").write_bytes(prepared.init_image_bytes)
        if prepared.mask_image_bytes:
            (output_dir / f"{prefix}_mask.png").write_bytes(prepared.mask_image_bytes)
        if prepared.reference_image_bytes:
            (output_dir / f"{prefix}_reference.png").write_bytes(
                prepared.reference_image_bytes
            )

        started = time.perf_counter()
        outputs = await provider.generate(
            input_image_bytes=prepared.init_image_bytes,
            mask_image_bytes=prepared.mask_image_bytes,
            reference_image_bytes=prepared.reference_image_bytes,
            prompt=prompt.prompt,
            prompt_2=prompt.prompt_2,
            negative_prompt=prompt.negative_prompt,
            num_images=1,
            size=get_variant_image_size(variant),
            render_mode=prepared.render_mode,
            img2img_strength=prepared.img2img_strength,
            inpaint_strength=prepared.inpaint_strength,
            ip_adapter_scale=prepared.ip_adapter_scale,
            num_inference_steps=prepared.num_inference_steps,
            guidance_scale=prepared.guidance_scale,
            seed=args.seed + index,
            variant=variant,
            variant_strategy=(
                "subject_inpaint"
                if prepared.render_mode == "background_swap"
                else "scene_img2img"
            ),
        )
        seconds = time.perf_counter() - started
        generated = image_bytes_to_pil(outputs[0]).convert("RGB")
        background_fallback_used = False
        if variant == "poster":
            generated.save(output_dir / "poster_before_overlay.png")
            quality = evaluate_poster_background(generated)
            if not quality.accepted and prepared.background_fallback_bytes:
                background_fallback_used = True
                generated = image_bytes_to_pil(
                    prepared.background_fallback_bytes
                ).convert("RGB").resize(generated.size, Image.Resampling.LANCZOS)

        if prepared.subject_layer_bytes:
            subject_layer = image_bytes_to_pil(
                prepared.subject_layer_bytes
            ).convert("RGBA")
            generated = recomposite_subject(generated, subject_layer)

        final_bytes = pil_image_to_png_bytes(generated)
        if variant_uses_pil_text_overlay(payload.food_type, variant):
            final_bytes = apply_variant_text_overlay(
                final_bytes,
                payload=payload,
                variant=variant,
            )
        final_path = output_dir / f"improved_{variant}.png"
        final_path.write_bytes(final_bytes)
        memory = collect_memory_snapshot(torch_module=torch)
        rows.append(
            {
                "variant": variant,
                "pipeline": (
                    "inpaint" if prepared.render_mode == "background_swap" else "img2img"
                ),
                "strength": (
                    prepared.inpaint_strength
                    if prepared.render_mode == "background_swap"
                    else prepared.img2img_strength
                ),
                "ip_adapter_scale": prepared.ip_adapter_scale,
                "seconds": round(seconds, 3),
                "peak_vram_gb": memory.get("gpu_peak_allocated_gb"),
                "background_fallback_used": background_fallback_used,
                "output": str(final_path.resolve()),
            }
        )

    _save_contact_sheet(output_dir)
    (output_dir / "smoke-results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return rows


def _save_contact_sheet(output_dir: Path) -> None:
    items = [
        ("input", output_dir / "input.png"),
        ("studio", output_dir / "improved_studio.png"),
        ("poster", output_dir / "improved_poster.png"),
        ("instagram", output_dir / "improved_instagram_feed.png"),
    ]
    tile_size = (512, 512)
    sheet = Image.new("RGB", (tile_size[0] * 2, tile_size[1] * 2), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, path) in enumerate(items):
        image = Image.open(path).convert("RGB")
        tile = ImageOps.contain(image, (tile_size[0], tile_size[1] - 28))
        x = (index % 2) * tile_size[0]
        y = (index // 2) * tile_size[1]
        sheet.paste(tile, (x + (tile_size[0] - tile.width) // 2, y + 28))
        draw.text((x + 12, y + 8), label, fill=(20, 20, 20))
    sheet.save(output_dir / "comparison.png")


def main() -> int:
    args = _parse_args()
    rows = asyncio.run(_run(args))
    print(json.dumps(rows, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
