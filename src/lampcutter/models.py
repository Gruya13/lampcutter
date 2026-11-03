"""Data types shared across the pipeline (specification, section 5).

Conventions used in this module:

* all coordinates in this module are pixels unless the field name says `_mm`;
* `bbox_px` is `(left, top, right, bottom)` with `right` and `bottom` exclusive
  (numpy slicing convention);
* `bbox_nominal_mm` follows `shapely.Geometry.bounds`: `(minx, miny, maxx, maxy)`;
* y grows downwards in both pixel and millimetre spaces (SVG convention).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
import shapely


@dataclass(frozen=True)
class Prompt:
    """User prompt for SAM 2: points, labels (1 = positive, 0 = negative) and box."""

    points: tuple[tuple[int, int], ...] = ()
    labels: tuple[int, ...] = ()
    box: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        if len(self.points) != len(self.labels):
            raise ValueError("Prompt.points and Prompt.labels must have the same length")
        wrong = [label for label in self.labels if label not in (0, 1)]
        if wrong:
            raise ValueError(f"Prompt.labels must be 0 or 1, got {wrong}")
        if self.box is not None:
            x0, y0, x1, y1 = self.box
            if x1 <= x0 or y1 <= y0:
                raise ValueError("Prompt.box must satisfy x1 > x0 and y1 > y0")

    @property
    def is_empty(self) -> bool:
        return not self.points and self.box is None


@dataclass
class SegmentationResult:
    """Output of one SAM 2 prediction (specification, 7.3)."""

    mask: np.ndarray  # bool, H x W, original image resolution
    score: float
    all_candidates: list[np.ndarray] = field(default_factory=list)


@dataclass(frozen=True)
class ScaleInfo:
    """Mapping from pixels to millimetres (specification, 7.5)."""

    mm_per_px: float
    reference: Literal["height", "width"]
    reference_mm: float  # refers to the cut part WITHOUT the tab
    bbox_px: tuple[int, int, int, int]

    def __post_init__(self) -> None:
        if self.mm_per_px <= 0:
            raise ValueError("ScaleInfo.mm_per_px must be positive")
        if self.reference_mm <= 0:
            raise ValueError("ScaleInfo.reference_mm must be positive")
        left, top, right, bottom = self.bbox_px
        if right <= left or bottom <= top:
            raise ValueError("ScaleInfo.bbox_px must satisfy right > left and bottom > top")

    @property
    def width_mm(self) -> float:
        return (self.bbox_px[2] - self.bbox_px[0]) * self.mm_per_px

    @property
    def height_mm(self) -> float:
        return (self.bbox_px[3] - self.bbox_px[1]) * self.mm_per_px


@dataclass(frozen=True)
class MaterialProfile:
    """Laser material profile (specification, 6.2)."""

    id: str
    name: str
    thickness_mm: float
    kerf_mm: float
    min_feature_mm: float = 1.5
    notes: str = ""


@dataclass(frozen=True)
class BaseProfile:
    """Base (stand) profile (specification, 6.3 and 8.3)."""

    id: str
    name: str
    slot_length_mm: float  # slot length in the plate plane
    slot_thickness_mm: float  # slot width across the acrylic thickness
    slot_dimensions: Literal["measured", "nominal_laser_cut"] = "measured"
    base_kerf_mm: float = 0.0  # only for "nominal_laser_cut"
    tab_width_mm: float = 0.0  # nominal width after cutting
    tab_height_mm: float = 0.0  # depth of insertion into the slot
    tab_fit_mm: float = 0.0  # manual correction (negative = narrower)
    tab_offset_mm: float = 0.0  # shift from the middle of the bottom contact
    corner_radius_mm: float = 0.5


@dataclass
class CutGeometry:
    """Nominal geometry and its kerf-compensated cut path (specification, 8.1)."""

    nominal: shapely.Polygon  # nominal part shape including the tab, in mm
    cut_path: shapely.Polygon  # the path the laser follows (after kerf offset)
    kerf_mm: float
    area_mm2: float
    bbox_nominal_mm: tuple[float, float, float, float]


@dataclass
class PhotoSlot:
    """Photo slot inside the lamp outline (specification, 9.1)."""

    id: str
    polygon_mm: shapely.Polygon  # nominal geometry, lamp coordinates
    source: Literal["detected", "manual", "full_outline"]
    image_path: Path | None = None
    fit: Literal["cover", "contain"] = "cover"
    zoom: float = 1.0
    offset_mm: tuple[float, float] = (0.0, 0.0)
    rotation_deg: float = 0.0
    bleed_mm: float | None = None  # None = default from config


@dataclass
class DecorElement:
    """Decor element: engraving or UV printing (specification, 9.3)."""

    id: str
    polygon_mm: shapely.Polygon | shapely.MultiPolygon
    source: Literal["sam_click", "threshold", "text"]
    mode: Literal["engrave", "print", "none"] = "engrave"
    engrave_style: Literal["fill", "line"] = "fill"
    color_override: str | None = None  # only for printing


@dataclass
class LampTemplate:
    """Complete lamp template, serialised as .lamptpl GeoJSON (specification, 9.2)."""

    outline: CutGeometry
    slots: list[PhotoSlot]
    decor: list[DecorElement]
    base: BaseProfile
    material: MaterialProfile
    scale: ScaleInfo
    input_kind: Literal["mockup", "photo"]
