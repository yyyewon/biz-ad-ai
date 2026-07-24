"""Real-GPU smoke test for SDXL img2img/inpaint with IP-Adapter Plus."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.model_config import get_model_settings  # noqa: E402
from app.services.providers.hf_sdxl_ip_adapter_provider import (  # noqa: E402
    HFSDXLIPAdapterImageProvider,
)
from app.utils.image_bytes import (  # noqa: E402
    image_bytes_to_pil,
    pil_image_to_png_bytes,
)
from app.utils.memory_monitor import collect_memory_snapshot  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load both SDXL pipelines and generate two real images.",
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument(
        "--prompt",
        default=(
            "professional commercial food photography, appetizing plated dish, "
            "natural texture, realistic studio lighting, clean premium background"
        ),
    )
    parser.add_argument("--img2img-strength", type=float, default=None)
    return parser.parse_args()


def _print_memory(label: str, torch_module: Any) -> dict[str, float | None]:
    snapshot = collect_memory_snapshot(torch_module=torch_module)
    print(
        f"{label} | peak_allocated_gb={snapshot.get('gpu_peak_allocated_gb')} | "
        f"peak_reserved_gb={snapshot.get('gpu_peak_reserved_gb')} | "
        f"allocated_gb={snapshot.get('gpu_memory_allocated_gb')} | "
        f"reserved_gb={snapshot.get('gpu_memory_reserved_gb')} | "
        f"process_rss_gb={snapshot.get('process_rss_gb')} | "
        f"ram_available_gb={snapshot.get('effective_available_ram_gb')}",
        flush=True,
    )
    return snapshot


def _build_background_mask(source: Image.Image) -> Image.Image:
    """White background is repainted; the central food region stays black."""
    width, height = source.size
    mask = Image.new("L", source.size, 255)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (
            int(width * 0.18),
            int(height * 0.18),
            int(width * 0.82),
            int(height * 0.82),
        ),
        radius=max(4, int(min(width, height) * 0.06)),
        fill=0,
    )
    return mask


async def _generate(
    provider: HFSDXLIPAdapterImageProvider,
    *,
    input_bytes: bytes,
    mask_bytes: bytes | None,
    prompt: str,
    size: str,
    render_mode: str,
    img2img_strength: float | None,
) -> list[bytes]:
    return await provider.generate(
        input_image_bytes=input_bytes,
        mask_image_bytes=mask_bytes,
        prompt=prompt,
        negative_prompt=(
            "blurry, low quality, distorted food, duplicate objects, text, "
            "watermark, logo, plastic texture"
        ),
        num_images=1,
        size=size,
        render_mode=render_mode,
        img2img_strength=img2img_strength,
    )


def main() -> int:
    args = _parse_args()
    if not args.input.is_file():
        raise FileNotFoundError(f"Real input image not found: {args.input}")

    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this smoke test")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = Image.open(args.input).convert("RGB")
    input_bytes = pil_image_to_png_bytes(source)
    mask = _build_background_mask(source)
    mask_bytes = pil_image_to_png_bytes(mask)
    mask_path = args.output_dir / "inpaint-mask.png"
    mask.save(mask_path)

    resolved = get_model_settings(
        role="image_generation",
        provider_name="hf",
    )
    model_settings = resolved["settings"]
    if str(model_settings.get("provider_type")) != "sdxl_ip_adapter":
        raise RuntimeError(
            "HF default image model must use provider_type=sdxl_ip_adapter"
        )
    provider = HFSDXLIPAdapterImageProvider(
        model_name=resolved["model_name"],
        model_settings=model_settings,
    )

    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    gpu = torch.cuda.get_device_properties(0)
    print(f"GPU model: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"total VRAM GB: {gpu.total_memory / 1024**3:.3f}", flush=True)
    print(f"torch: {torch.__version__}", flush=True)
    print(f"CUDA: {torch.version.cuda}", flush=True)
    print(f"HF_HOME: {os.getenv('HF_HOME', '(unset)')}", flush=True)
    _print_memory("startup memory", torch)

    load_started = time.perf_counter()
    base_pipe, base_meta = provider._load_pipeline("img2img")
    base_load_seconds = time.perf_counter() - load_started
    print(f"Base load time seconds: {base_load_seconds:.3f}", flush=True)
    print(f"Base IP-Adapter loaded: {base_meta['ip_adapter_enabled']}", flush=True)
    del base_pipe
    _print_memory("after Base load", torch)

    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    inference_started = time.perf_counter()
    img2img_outputs = asyncio.run(
        _generate(
            provider,
            input_bytes=input_bytes,
            mask_bytes=None,
            prompt=args.prompt,
            size=args.size,
            render_mode="photo_restyle",
            img2img_strength=args.img2img_strength,
        )
    )
    img2img_seconds = time.perf_counter() - inference_started
    img2img_path = args.output_dir / "sdxl-img2img.png"
    img2img_path.write_bytes(img2img_outputs[0])
    print(f"Img2Img inference time seconds: {img2img_seconds:.3f}", flush=True)
    print(f"Img2Img output path: {img2img_path.resolve()}", flush=True)
    _print_memory("after Img2Img inference", torch)

    load_started = time.perf_counter()
    inpaint_pipe, inpaint_meta = provider._load_pipeline("inpaint")
    inpaint_load_seconds = time.perf_counter() - load_started
    print(f"Inpaint load time seconds: {inpaint_load_seconds:.3f}", flush=True)
    print(
        f"Inpaint IP-Adapter loaded: {inpaint_meta['ip_adapter_enabled']}",
        flush=True,
    )
    del inpaint_pipe
    _print_memory("after Inpaint load", torch)

    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    inference_started = time.perf_counter()
    inpaint_outputs = asyncio.run(
        _generate(
            provider,
            input_bytes=input_bytes,
            mask_bytes=mask_bytes,
            prompt=args.prompt + ", replace only the background",
            size=args.size,
            render_mode="background_swap",
            img2img_strength=None,
        )
    )
    inpaint_seconds = time.perf_counter() - inference_started
    inpaint_path = args.output_dir / "sdxl-inpaint.png"
    inpaint_path.write_bytes(inpaint_outputs[0])
    print(f"Inpaint inference time seconds: {inpaint_seconds:.3f}", flush=True)
    print(f"Inpaint output path: {inpaint_path.resolve()}", flush=True)
    print(f"Inpaint mask path: {mask_path.resolve()}", flush=True)
    _print_memory("after Inpaint inference", torch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
