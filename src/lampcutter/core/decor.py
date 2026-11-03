"""Decor extraction and validation (specification, 9.1 and 9.3).

Decor elements are extracted two ways: a SAM 2 click (coarse shapes) or a
threshold/colour selection inside a user-drawn rectangle (thin lines and text,
where SAM often fails). Each element is later engraved, printed or ignored.
"""

from __future__ import annotations

from typing import Literal

import cv2
import numpy as np
from shapely.geometry import Polygon

from lampcutter.config import Config
from lampcutter.core import geometry
from lampcutter.core.vectorize import contour_to_mm, make_backend, upsample_factor
from lampcutter.models import DecorElement, MaterialProfile, ScaleInfo

ThresholdMode = Literal["luminance", "color"]


class DecorError(ValueError):
    """The decor selection produced no usable geometry."""


def crop_zone(image: np.ndarray, zone: tuple[int, int, int, int]) -> np.ndarray:
    """Crop `(x0, y0, x1, y1)` from an H x W x 3 image, clamping to its size."""
    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError("image must be H x W x 3")
    x0, y0, x1, y1 = zone
    height, width = image.shape[:2]
    x0, x1 = max(0, x0), min(width, x1)
    y0, y1 = max(0, y0), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("prazna zona za izdvajanje dekora")
    return image[y0:y1, x0:x1, :3]


def threshold_mask(
    image: np.ndarray,
    zone: tuple[int, int, int, int],
    mode: ThresholdMode = "luminance",
    threshold: float | None = None,
) -> tuple[np.ndarray, float]:
    """Return `(mask, used_threshold)` for the selected decor inside the zone.

    `luminance` keeps pixels darker than the threshold (text and line art on a
    light background); `threshold=None` picks an adaptive (Otsu) threshold.
    `color` keeps pixels close to the median colour of the zone.
    """
    crop = crop_zone(image, zone)
    if mode == "luminance":
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        if threshold is None:
            # Otsu returns the threshold, but cv2 computes the binary image itself:
            # on a strictly bimodal crop Otsu's threshold lands on the dark value,
            # so "gray < threshold" would drop the object.
            used, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            return binary > 0, float(used)
        return gray.astype(np.float32) < float(threshold), float(threshold)
    if mode == "color":
        lab = cv2.cvtColor(crop, cv2.COLOR_RGB2LAB).astype(np.float32)
        median = np.median(lab.reshape(-1, 3), axis=0)
        distance = np.linalg.norm(lab - median, axis=2)
        used = float(threshold) if threshold is not None else float(np.median(distance) * 2.0)
        return distance > used, used
    raise ValueError(f"nepoznat režim praga {mode!r}")


def decor_polygons_from_mask(
    mask: np.ndarray,
    mm_per_px: float,
    origin_px: tuple[int, int] = (0, 0),
    config: Config | None = None,
) -> list[Polygon]:
    """Vectorise a zone mask into decor polygons in absolute millimetres."""
    cfg = config or Config()
    binary = mask.astype(bool, copy=False)
    if not binary.any():
        return []
    upscale = max(1, int(cfg.decor_upsample))
    backend = make_backend(cfg)
    factor = upsample_factor(binary, cfg)
    flatten_tol_px = cfg.curve_sample_tol_mm / mm_per_px
    contours = backend.trace(binary, flatten_tol_px, factor * upscale)
    offset_x, offset_y = origin_px
    polygons: list[Polygon] = []
    for contour in contours:
        points = [((x + offset_x) * mm_per_px, (y + offset_y) * mm_per_px) for x, y in contour]
        contour_mm = contour_to_mm(points, 1.0, min_edge_mm=cfg.min_edge_mm)
        if contour_mm.area > 0:
            polygons.append(contour_mm)
    polygons.sort(key=lambda item: item.area, reverse=True)
    return polygons


def decor_from_threshold(
    image: np.ndarray,
    zone: tuple[int, int, int, int],
    scale: ScaleInfo,
    mode: ThresholdMode = "luminance",
    threshold: float | None = None,
    config: Config | None = None,
) -> list[Polygon]:
    """Extract decor polygons inside a zone with a luminance/colour threshold."""
    cfg = config or Config()
    mask, _used = threshold_mask(image, zone, mode, threshold)
    return decor_polygons_from_mask(
        mask,
        scale.mm_per_px,
        origin_px=(zone[0], zone[1]),
        config=cfg,
    )


def decor_from_mask(
    mask: np.ndarray,
    scale: ScaleInfo,
    config: Config | None = None,
) -> list[Polygon]:
    """Turn a SAM 2 click mask (full image resolution) into decor polygons."""
    cfg = config or Config()
    return decor_polygons_from_mask(mask, scale.mm_per_px, config=cfg)


def element_from_polygon(
    element_id: str,
    polygon: Polygon,
    source: Literal["sam_click", "threshold", "text"] = "threshold",
    mode: Literal["engrave", "print", "none"] = "engrave",
) -> DecorElement:
    """Wrap a polygon into a `DecorElement`."""
    return DecorElement(id=element_id, polygon_mm=polygon, source=source, mode=mode)


def engrave_polygons(elements: list[DecorElement]) -> list[Polygon]:
    """Polygons that belong to the engrave layer of the cut SVG."""
    return [element.polygon_mm for element in elements if element.mode == "engrave"]


def print_elements(elements: list[DecorElement]) -> list[DecorElement]:
    """Elements that belong to the print sheet and per-element PNGs."""
    return [element for element in elements if element.mode == "print"]


def validate_decor_in_outline(
    elements: list[DecorElement],
    outline_nominal,
    margin_mm: float,
) -> list[str]:
    """Every element must sit inside `outline.buffer(-margin)` (specification, 9.3)."""
    if margin_mm < 0:
        raise ValueError("margin_mm must be non-negative")
    allowed = outline_nominal.buffer(-margin_mm)
    warnings: list[str] = []
    for element in elements:
        if element.mode == "none":
            continue
        if not allowed.contains(element.polygon_mm):
            warnings.append(
                f"dekor '{element.id}' izlazi iz konture ili je bliži od {margin_mm:g} mm"
            )
    return warnings


def decor_warnings(
    elements: list[DecorElement],
    outline_nominal,
    material: MaterialProfile,
    margin_mm: float,
    config: Config | None = None,
) -> list[str]:
    """All decor warnings: outline margin and lines thinner than the material allows."""
    cfg = config or Config()
    warnings = validate_decor_in_outline(elements, outline_nominal, margin_mm)
    for element in elements:
        if element.mode == "none":
            continue
        thin = geometry.find_thin_regions(element.polygon_mm, material.min_feature_mm)
        if not thin.is_empty and thin.area > cfg.thin_feature_min_area_mm2:
            warnings.append(
                f"dekor '{element.id}' ima linije tanje od {material.min_feature_mm:g} mm"
            )
    return warnings
