"""Mask cleanup primitives (specification, 7.4).

Every operation is a separate, individually testable function. All functions
take and return boolean `np.ndarray` masks of shape `(height, width)`, with
`True` meaning "part of the lamp". y grows downwards.
"""

from __future__ import annotations

import cv2
import numpy as np

from lampcutter.config import Config


def _check_mask(mask: np.ndarray) -> np.ndarray:
    if mask.ndim != 2:
        raise ValueError("mask must be a 2-D array")
    return mask.astype(bool, copy=False)


def components(mask: np.ndarray) -> list[np.ndarray]:
    """Return connected components as boolean masks, largest area first."""
    binary = _check_mask(mask).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    found: list[np.ndarray] = []
    for label in range(1, count):  # 0 is the background
        if stats[label, cv2.CC_STAT_AREA] == 0:
            continue
        found.append(labels == label)
    found.sort(key=lambda item: int(item.sum()), reverse=True)
    return found


def count_components(mask: np.ndarray) -> int:
    """Number of connected components (specification, 8.4)."""
    return len(components(mask))


def largest_component(mask: np.ndarray) -> np.ndarray:
    """Keep only the largest connected component (specification, 7.4 step 1)."""
    found = components(mask)
    if not found:
        return np.zeros_like(_check_mask(mask))
    return found[0]


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """Fill every interior hole; v1 cuts only the outer contour (7.4 step 2)."""
    binary = _check_mask(mask)
    contours, _ = cv2.findContours(
        binary.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    filled = np.zeros_like(binary, dtype=np.uint8)
    cv2.drawContours(filled, contours, -1, 1, thickness=cv2.FILLED)
    return filled.astype(bool)


def morph_close(mask: np.ndarray, radius_px: int) -> np.ndarray:
    """Morphological closing with an elliptical kernel (specification, 7.4 step 3)."""
    if radius_px < 0:
        raise ValueError("radius_px must be non-negative")
    binary = _check_mask(mask).astype(np.uint8)
    if radius_px == 0:
        return binary.astype(bool)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius_px + 1, 2 * radius_px + 1))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    return closed.astype(bool)


def smooth(mask: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur followed by a 0.5 threshold (specification, 7.4 step 4)."""
    if sigma < 0:
        raise ValueError("sigma must be non-negative")
    binary = _check_mask(mask)
    if sigma == 0:
        return binary.copy()
    blurred = cv2.GaussianBlur(binary.astype(np.float32), (0, 0), sigmaX=sigma)
    return blurred >= 0.5


def cut_at_line(mask: np.ndarray, y_px: int) -> np.ndarray:
    """Keep everything above a straight line: the base starts at `y_px` (7.4 step 6).

    y grows downwards, so rows `y_px` and below are cleared.
    """
    binary = _check_mask(mask)
    if y_px < 0:
        raise ValueError("y_px must be non-negative")
    cut = binary.copy()
    cut[y_px:, :] = False
    return cut


def remove_stand(mask: np.ndarray, line: int) -> np.ndarray:
    """Straight bottom cut; alias of `cut_at_line` (specification, 7.4 step 6)."""
    return cut_at_line(mask, line)


def polygon_to_mask(
    points: list[tuple[int, int]] | np.ndarray,
    shape: tuple[int, int],
) -> np.ndarray:
    """Rasterise a manual polygon into a boolean mask (specification, 7.4 step 7)."""
    if len(points) < 3:
        raise ValueError("a polygon needs at least 3 points")
    height, width = shape
    canvas = np.zeros((height, width), dtype=np.uint8)
    pts = np.asarray(points, dtype=np.int32).reshape(-1, 1, 2)
    cv2.fillPoly(canvas, [pts], 1)
    return canvas.astype(bool)


def clean_mask(mask: np.ndarray, config: Config) -> np.ndarray:
    """Clean a raw SAM 2 mask into a solid, smooth single-component mask.

    Order (specification, 8.2 and 7.4): smooth -> largest component ->
    morphological close -> fill holes. The multi-component case (8.4) is
    reported by the pipeline before this function is called.
    """
    binary = _check_mask(mask)
    if not binary.any():
        return binary
    denoised = smooth(binary, config.mask_smooth_sigma_px)
    largest = largest_component(denoised)
    closed = morph_close(largest, radius_px=1)
    return fill_holes(closed)
