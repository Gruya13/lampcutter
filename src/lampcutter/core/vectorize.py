"""Raster-to-vector conversion (specification, 7.6).

A binary mask becomes a closed `shapely.Polygon` in millimetres. Potrace is the
primary backend; OpenCV contours + Douglas-Peucker + Chaikin is a drop-in
replacement behind the same `VectorizeBackend` protocol.

Coordinate conventions: the backend works in pixel coordinates that match numpy
indices (y grows downwards); `vectorize_mask` multiplies by `mm_per_px`, so the
result is also y-down in millimetres.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np
import potrace
import shapely
from shapely.geometry import Polygon

from lampcutter.config import Config
from lampcutter.core.geometry import clean_ring
from lampcutter.models import ScaleInfo

Point = tuple[float, float]


class VectorizeError(ValueError):
    """The mask could not be converted into a valid polygon."""


class VectorizeBackend(Protocol):
    """Interface every raster-to-vector backend implements."""

    name: str

    def trace(
        self,
        mask: np.ndarray,
        flatten_tol_px: float,
        upscale: int,
    ) -> list[list[Point]]:
        """Return closed contours in original pixel coordinates."""


@dataclass(frozen=True)
class PotraceBackend:
    """Potrace (pure Python port) backend (specification, 7.6)."""

    name: str = "potrace"
    turdsize: int = 20
    alphamax: float = 1.0
    opttolerance: float = 0.2

    def trace(
        self,
        mask: np.ndarray,
        flatten_tol_px: float,
        upscale: int,
    ) -> list[list[Point]]:
        return _trace_with_potrace(
            mask,
            flatten_tol_px,
            upscale,
            turdsize=self.turdsize,
            alphamax=self.alphamax,
            opttolerance=self.opttolerance,
        )


@dataclass(frozen=True)
class Cv2Backend:
    """OpenCV contours + Douglas-Peucker + Chaikin fallback (specification, 7.6)."""

    name: str = "cv2"
    chaikin_iterations: int = 2

    def trace(
        self,
        mask: np.ndarray,
        flatten_tol_px: float,
        upscale: int,
    ) -> list[list[Point]]:
        return _trace_with_cv2(mask, flatten_tol_px, upscale, self.chaikin_iterations)


def make_backend(config: Config) -> VectorizeBackend:
    """Pick the configured backend."""
    if config.vectorize_backend == "potrace":
        return PotraceBackend(
            turdsize=config.potrace_turdsize,
            alphamax=config.potrace_alphamax,
            opttolerance=config.potrace_opttolerance,
        )
    if config.vectorize_backend == "cv2":
        return Cv2Backend()
    raise VectorizeError(f"unknown vectorize backend {config.vectorize_backend!r}")


def upsample_factor(mask: np.ndarray, config: Config) -> int:
    """2x bitmap for low-resolution masks (specification, 7.6 step 1)."""
    return 2 if max(mask.shape) < config.vectorize_upsample_threshold_px else 1


def _upsampled(mask: np.ndarray, factor: int) -> np.ndarray:
    if factor == 1:
        return mask
    enlarged = cv2.resize(
        mask.astype(np.float32),
        (mask.shape[1] * factor, mask.shape[0] * factor),
        interpolation=cv2.INTER_CUBIC,
    )
    return enlarged >= 0.5


def _flatten_cubic(
    p0: Point,
    c1: Point,
    c2: Point,
    p3: Point,
    tolerance: float,
    out: list[Point],
    depth: int = 0,
    max_depth: int = 14,
) -> None:
    """Adaptive de Casteljau subdivision until the curve is within `tolerance`."""
    if depth >= max_depth:
        out.append(p3)
        return
    length = float(np.hypot(p3[0] - p0[0], p3[1] - p0[1]))
    if length > 1e-12:
        chord1 = abs((p3[0] - p0[0]) * (c1[1] - p0[1]) - (c1[0] - p0[0]) * (p3[1] - p0[1]))
        chord2 = abs((p3[0] - p0[0]) * (c2[1] - p0[1]) - (c2[0] - p0[0]) * (p3[1] - p0[1]))
        if max(chord1, chord2) / length <= tolerance:
            out.append(p3)
            return
    mid01 = ((p0[0] + c1[0]) / 2, (p0[1] + c1[1]) / 2)
    mid12 = ((c1[0] + c2[0]) / 2, (c1[1] + c2[1]) / 2)
    mid23 = ((c2[0] + p3[0]) / 2, (c2[1] + p3[1]) / 2)
    mid012 = ((mid01[0] + mid12[0]) / 2, (mid01[1] + mid12[1]) / 2)
    mid123 = ((mid12[0] + mid23[0]) / 2, (mid12[1] + mid23[1]) / 2)
    midpoint = ((mid012[0] + mid123[0]) / 2, (mid012[1] + mid123[1]) / 2)
    _flatten_cubic(p0, mid01, mid012, midpoint, tolerance, out, depth + 1, max_depth)
    _flatten_cubic(midpoint, mid123, mid23, p3, tolerance, out, depth + 1, max_depth)


def _trace_with_potrace(
    mask: np.ndarray,
    flatten_tol_px: float,
    upscale: int,
    turdsize: int,
    alphamax: float,
    opttolerance: float,
) -> list[list[Point]]:
    bitmap = _upsampled(mask, upscale)
    # potracer inverts numpy input internally, so pass the background as True.
    traced = potrace.Bitmap(~bitmap).trace(
        turdsize=turdsize,
        alphamax=alphamax,
        opttolerance=opttolerance,
    )
    tolerance = flatten_tol_px / upscale
    contours: list[list[Point]] = []
    for curve in traced.curves:
        start = curve.start_point
        ring: list[Point] = [(start.x / upscale, start.y / upscale)]
        current = (start.x, start.y)
        for segment in curve.segments:
            if segment.is_corner:
                corner = segment.c
                end = segment.end_point
                ring.append((corner.x / upscale, corner.y / upscale))
                ring.append((end.x / upscale, end.y / upscale))
                current = (end.x, end.y)
            else:
                control1 = segment.c1
                control2 = segment.c2
                end = segment.end_point
                points: list[Point] = []
                _flatten_cubic(
                    current,
                    (control1.x, control1.y),
                    (control2.x, control2.y),
                    (end.x, end.y),
                    tolerance,
                    points,
                )
                ring.extend((x / upscale, y / upscale) for x, y in points)
                current = (end.x, end.y)
        if len(ring) >= 3:
            contours.append(ring)
    return contours


def _chaikin(points: list[Point], iterations: int) -> list[Point]:
    """Chaikin corner cutting: smooths a polygon while keeping it closed."""
    ring = points
    for _ in range(iterations):
        if len(ring) < 3:
            return ring
        smoothed: list[Point] = []
        count = len(ring)
        for index in range(count):
            x0, y0 = ring[index]
            x1, y1 = ring[(index + 1) % count]
            smoothed.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            smoothed.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        ring = smoothed
    return ring


def _trace_with_cv2(
    mask: np.ndarray,
    flatten_tol_px: float,
    upscale: int,
    chaikin_iterations: int,
) -> list[list[Point]]:
    bitmap = _upsampled(mask, upscale)
    contours, _ = cv2.findContours(
        bitmap.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    rings: list[list[Point]] = []
    for contour in contours:
        epsilon = max(flatten_tol_px * upscale, 1e-6)
        approximated = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        points = [(float(x) / upscale, float(y) / upscale) for x, y in approximated]
        if len(points) < 3:
            continue
        rings.append(_chaikin(points, chaikin_iterations))
    return rings


def contour_to_mm(
    contour: list[Point],
    mm_per_px: float,
    min_edge_mm: float = 0.0,
) -> Polygon:
    """Convert a closed pixel contour into a shapely polygon in millimetres."""
    if len(contour) < 3:
        raise VectorizeError("kontura ima manje od 3 tačke")
    points = [(x * mm_per_px, y * mm_per_px) for x, y in contour]
    points = clean_ring(points, min_edge_mm)
    if len(points) < 3:
        raise VectorizeError("kontura ima manje od 3 tačke nakon uklanjanja kratkih ivica")
    polygon = Polygon(points)
    if not polygon.is_valid:
        polygon = shapely.make_valid(polygon)
    if isinstance(polygon, Polygon):
        return polygon
    parts = [part for part in shapely.get_parts(polygon) if isinstance(part, Polygon)]
    if not parts:
        raise VectorizeError("kontura nije dala nijedan poligon")
    return max(parts, key=lambda item: item.area)


def vectorize_mask(
    mask: np.ndarray,
    scale: ScaleInfo,
    config: Config,
) -> Polygon:
    """Convert a binary mask into the largest polygon in millimetres (specification, 7.6)."""
    binary = mask.astype(bool, copy=False)
    if binary.ndim != 2:
        raise VectorizeError("maska mora biti 2-D")
    if not binary.any():
        raise VectorizeError("maska je prazna")
    backend = make_backend(config)
    factor = upsample_factor(binary, config)
    flatten_tol_px = config.curve_sample_tol_mm / scale.mm_per_px
    contours = backend.trace(binary, flatten_tol_px, factor)
    if not contours:
        raise VectorizeError("vektorizacija nije dala nijednu konturu")
    polygons = [
        contour_to_mm(contour, scale.mm_per_px, min_edge_mm=config.min_edge_mm)
        for contour in contours
    ]
    polygons = [polygon for polygon in polygons if polygon.area > 0]
    if not polygons:
        raise VectorizeError("sve konture su prazne")
    polygon = max(polygons, key=lambda item: item.area)
    if polygon.exterior is None or len(polygon.exterior.coords) < 4:
        raise VectorizeError("kontura nema dovoljno tačaka")
    return polygon
