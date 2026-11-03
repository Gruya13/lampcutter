"""Pixel-to-millimetre scale (specification, 7.5)."""

from __future__ import annotations

import warnings

import numpy as np

from lampcutter.models import ScaleInfo

# Specification, 7.5: warn when the bounding-box aspect ratio is unexpected.
DEFAULT_ASPECT_WARN_RATIO = 10.0


class SuspiciousAspectRatioWarning(UserWarning):
    """The bounding box looks like it cannot be a frontal lamp plate."""


def mask_bbox_px(mask: np.ndarray) -> tuple[int, int, int, int]:
    """Bounding box of the `True` pixels as `(left, top, right, bottom)`, right/bottom exclusive."""
    binary = mask.astype(bool, copy=False)
    if not binary.any():
        raise ValueError("mask is empty; cannot compute a bounding box")
    rows = np.flatnonzero(binary.any(axis=1))
    cols = np.flatnonzero(binary.any(axis=0))
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def compute_scale(
    mask: np.ndarray,
    reference: str,
    reference_mm: float,
    aspect_warn_ratio: float = DEFAULT_ASPECT_WARN_RATIO,
) -> ScaleInfo:
    """Compute `mm_per_px` from one known real dimension (specification, 7.5).

    `reference` is `"height"` or `"width"` of the cut part (without the tab).
    """
    if reference not in ("height", "width"):
        raise ValueError("reference must be 'height' or 'width'")
    if reference_mm <= 0:
        raise ValueError("reference_mm must be positive")
    bbox = mask_bbox_px(mask)
    width_px = bbox[2] - bbox[0]
    height_px = bbox[3] - bbox[1]
    dimension_px = height_px if reference == "height" else width_px
    if dimension_px <= 0:
        raise ValueError("mask has zero size along the reference axis")
    aspect = width_px / height_px
    if aspect > aspect_warn_ratio or aspect < 1.0 / aspect_warn_ratio:
        warnings.warn(
            f"Odnos strana konture je neuobičajen ({width_px}x{height_px} px); "
            f"proveri referentnu dimenziju i masku.",
            SuspiciousAspectRatioWarning,
            stacklevel=2,
        )
    return ScaleInfo(
        mm_per_px=reference_mm / dimension_px,
        reference=reference,  # type: ignore[arg-type]
        reference_mm=reference_mm,
        bbox_px=bbox,
    )


def compute_scale_from_points(
    p1: tuple[float, float],
    p2: tuple[float, float],
    known_mm: float,
) -> float:
    """Two-point calibration with a reference object (specification, 7.5).

    Returns `mm_per_px`; `p1` and `p2` are in pixels.
    """
    if known_mm <= 0:
        raise ValueError("known_mm must be positive")
    distance_px = float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
    if distance_px <= 0:
        raise ValueError("the two calibration points must differ")
    return known_mm / distance_px
