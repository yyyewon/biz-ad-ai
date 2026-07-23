"""Shared food foreground extraction for SDXL variant composition."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from loguru import logger
from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat

from app.utils.poster_layout import _detect_foreground_alpha


_MASK_WORKING_SIDE = 256
_MIN_SUBJECT_AREA_RATIO = 0.025
_MAX_SUBJECT_AREA_RATIO = 0.78
_MIN_SUBJECT_BBOX_RATIO = 0.04
_MAX_SUBJECT_BBOX_RATIO = 0.88


@dataclass(frozen=True)
class PreparedFoodSubject:
    source_rgb: Image.Image
    subject_rgba: Image.Image | None
    subject_alpha: Image.Image | None
    subject_bbox: tuple[int, int, int, int] | None
    reference_rgb: Image.Image
    segmentation_valid: bool
    fallback_reason: str | None
    subject_area_ratio: float


def prepare_food_subject(source: Image.Image) -> PreparedFoodSubject:
    """Run rembg once, clean its mask, and build a background-free reference."""

    source_rgb = ImageOps.exif_transpose(source).convert("RGB")
    try:
        raw_alpha = _detect_foreground_alpha(source_rgb)
        alpha = _clean_subject_alpha(raw_alpha)
    except Exception as exc:
        logger.warning(
            "food_subject_segmentation_failed | error_type={} | error={}",
            exc.__class__.__name__,
            str(exc),
        )
        return _fallback_subject(source_rgb, f"rembg_error:{exc.__class__.__name__}")

    bbox = alpha.getbbox()
    area_ratio = _alpha_area_ratio(alpha)
    reason = _validate_subject(alpha, bbox, area_ratio)
    if reason is not None:
        logger.warning(
            "food_subject_segmentation_invalid | reason={} | bbox={} | area_ratio={:.4f}",
            reason,
            bbox,
            area_ratio,
        )
        return _fallback_subject(source_rgb, reason, alpha=alpha, area_ratio=area_ratio)

    subject_rgba = source_rgb.convert("RGBA")
    subject_rgba.putalpha(alpha)
    reference_rgb = _build_subject_reference(subject_rgba, bbox)
    logger.info(
        "food_subject_prepared | bbox={} | area_ratio={:.4f} | reference_size={}",
        bbox,
        area_ratio,
        reference_rgb.size,
    )
    return PreparedFoodSubject(
        source_rgb=source_rgb,
        subject_rgba=subject_rgba,
        subject_alpha=alpha,
        subject_bbox=bbox,
        reference_rgb=reference_rgb,
        segmentation_valid=True,
        fallback_reason=None,
        subject_area_ratio=area_ratio,
    )


def _clean_subject_alpha(alpha: Image.Image) -> Image.Image:
    """Remove detached receipt/chair noise while retaining nearby plate pieces."""

    alpha = alpha.convert("L")
    width, height = alpha.size
    scale = min(1.0, _MASK_WORKING_SIDE / max(width, height))
    work_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    work = alpha.resize(work_size, Image.Resampling.LANCZOS)
    binary = work.point(lambda value: 255 if value >= 72 else 0)
    binary = binary.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))

    components = _connected_components(binary)
    if not components:
        return Image.new("L", alpha.size, 0)

    main = max(components, key=lambda item: _component_score(item, work_size))
    main_pixels, main_bbox = main
    main_area = len(main_pixels)
    keep: list[tuple[list[tuple[int, int]], tuple[int, int, int, int]]] = [main]
    expanded = _expand_bbox(main_bbox, work_size, 0.18)
    for component in components:
        if component is main:
            continue
        pixels, bbox = component
        minimum_area = max(10, int(main_area * 0.045))
        if len(pixels) < minimum_area:
            continue
        if _boxes_touch(bbox, expanded):
            keep.append(component)

    kept = Image.new("L", work_size, 0)
    kept_pixels = kept.load()
    for pixels, _ in keep:
        for x, y in pixels:
            kept_pixels[x, y] = 255

    kept = kept.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(3))
    kept = kept.resize(alpha.size, Image.Resampling.LANCZOS)
    cleaned = ImageChops.multiply(alpha, kept)
    return cleaned.filter(ImageFilter.GaussianBlur(radius=1.2))


def _connected_components(
    binary: Image.Image,
) -> list[tuple[list[tuple[int, int]], tuple[int, int, int, int]]]:
    pixels = binary.load()
    width, height = binary.size
    visited = bytearray(width * height)
    components: list[tuple[list[tuple[int, int]], tuple[int, int, int, int]]] = []

    for y in range(height):
        for x in range(width):
            index = y * width + x
            if visited[index] or pixels[x, y] == 0:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            visited[index] = 1
            component: list[tuple[int, int]] = []
            left = right = x
            top = bottom = y
            while queue:
                px, py = queue.popleft()
                component.append((px, py))
                left = min(left, px)
                right = max(right, px)
                top = min(top, py)
                bottom = max(bottom, py)
                for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    neighbor_index = ny * width + nx
                    if visited[neighbor_index] or pixels[nx, ny] == 0:
                        continue
                    visited[neighbor_index] = 1
                    queue.append((nx, ny))
            components.append((component, (left, top, right + 1, bottom + 1)))
    return components


def _component_score(
    component: tuple[list[tuple[int, int]], tuple[int, int, int, int]],
    size: tuple[int, int],
) -> float:
    pixels, bbox = component
    width, height = size
    center_x = (bbox[0] + bbox[2]) / 2 / width
    center_y = (bbox[1] + bbox[3]) / 2 / height
    center_weight = max(0.25, 1.0 - abs(center_x - 0.5))
    lower_weight = 0.8 + 0.4 * center_y
    return len(pixels) * center_weight * lower_weight


def _expand_bbox(
    bbox: tuple[int, int, int, int],
    size: tuple[int, int],
    ratio: float,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    width, height = size
    margin_x = int((right - left) * ratio)
    margin_y = int((bottom - top) * ratio)
    return (
        max(0, left - margin_x),
        max(0, top - margin_y),
        min(width, right + margin_x),
        min(height, bottom + margin_y),
    )


def _boxes_touch(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> bool:
    return not (
        first[2] < second[0]
        or first[0] > second[2]
        or first[3] < second[1]
        or first[1] > second[3]
    )


def _alpha_area_ratio(alpha: Image.Image) -> float:
    total = alpha.width * alpha.height * 255
    return float(ImageStat.Stat(alpha).sum[0] / total) if total else 0.0


def _validate_subject(
    alpha: Image.Image,
    bbox: tuple[int, int, int, int] | None,
    area_ratio: float,
) -> str | None:
    if bbox is None:
        return "empty_mask"
    bbox_area = max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])
    image_area = alpha.width * alpha.height
    bbox_ratio = bbox_area / image_area if image_area else 0.0
    if not _MIN_SUBJECT_AREA_RATIO <= area_ratio <= _MAX_SUBJECT_AREA_RATIO:
        return "subject_area_out_of_range"
    if not _MIN_SUBJECT_BBOX_RATIO <= bbox_ratio <= _MAX_SUBJECT_BBOX_RATIO:
        return "subject_bbox_out_of_range"
    return None


def _build_subject_reference(
    subject_rgba: Image.Image,
    bbox: tuple[int, int, int, int],
    *,
    size: tuple[int, int] = (512, 512),
) -> Image.Image:
    crop = subject_rgba.crop(bbox)
    alpha = crop.getchannel("A")
    mean = ImageStat.Stat(crop.convert("RGB"), mask=alpha).mean
    neutral = tuple(int(channel * 0.18 + 218 * 0.82) for channel in mean)
    canvas = Image.new("RGBA", size, (*neutral, 255))
    target_w = int(size[0] * 0.80)
    target_h = int(size[1] * 0.80)
    scale = min(target_w / crop.width, target_h / crop.height)
    resized = crop.resize(
        (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
        Image.Resampling.LANCZOS,
    )
    offset = ((size[0] - resized.width) // 2, (size[1] - resized.height) // 2)
    canvas.alpha_composite(resized, offset)
    return canvas.convert("RGB")


def _fallback_subject(
    source_rgb: Image.Image,
    reason: str,
    *,
    alpha: Image.Image | None = None,
    area_ratio: float = 0.0,
) -> PreparedFoodSubject:
    reference = ImageOps.pad(
        source_rgb,
        (512, 512),
        method=Image.Resampling.LANCZOS,
        color=(218, 216, 212),
    )
    return PreparedFoodSubject(
        source_rgb=source_rgb,
        subject_rgba=None,
        subject_alpha=alpha,
        subject_bbox=None,
        reference_rgb=reference,
        segmentation_valid=False,
        fallback_reason=reason,
        subject_area_ratio=area_ratio,
    )
