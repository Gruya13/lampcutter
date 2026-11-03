"""Configuration and defaults (specification, section 6.1).

Values marked `# PROVISIONAL` must not be treated as final: they are confirmed
(or corrected) by the gloss experiment in phase E or by a physical test cut.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

KerfMode = Literal["app", "lightburn"]
InputKind = Literal["mockup", "photo"]
SamVariant = Literal["auto", "tiny", "small", "base_plus", "large"]
DeviceName = Literal["auto", "cuda", "mps", "cpu"]
VectorizeBackend = Literal["potrace", "cv2"]
PrintOrder = Literal["cut_then_print", "print_then_cut"]

VALID_KERF_MODES: tuple[str, ...] = ("app", "lightburn")
VALID_INPUT_KINDS: tuple[str, ...] = ("mockup", "photo")
VALID_SAM_VARIANTS: tuple[str, ...] = ("auto", "tiny", "small", "base_plus", "large")
VALID_DEVICES: tuple[str, ...] = ("auto", "cuda", "mps", "cpu")
VALID_BACKENDS: tuple[str, ...] = ("potrace", "cv2")


@dataclass
class Config:
    """Runtime configuration (specification, 6.1); CLI arguments override it."""

    sam_variant: SamVariant = "auto"
    device: DeviceName = "auto"
    max_side_px: int = 2048  # does not shrink the encoder (always 1024x1024)
    mask_min_component_frac: float = 0.001
    mask_hole_min_area_mm2: float = 4.0
    mask_smooth_sigma_px: float = 2.0
    # PROVISIONAL (specification, 17): edge refinement band for real photos.
    refine_edge_photo: bool = True
    refine_edge_band_px: int = 8
    # Phase 1: slots, decor and print (specification, 9.3 and 9.4).
    print_order: PrintOrder = "cut_then_print"
    slot_photo_min_dpi: float = 150.0
    decor_ink_color: str = "#000000"
    # PROVISIONAL (specification, 9.4, 17): registration marks and slot checks.
    registration_mark_size_mm: float = 5.0
    registration_mark_offset_mm: float = 5.0
    registration_mark_circle_radius_mm: float = 1.0
    slot_solidity_min: float = 0.5
    slot_overlap_max: float = 0.1
    slot_min_area_mm2: float = 50.0
    decor_upsample: int = 2
    potrace_turdsize: int = 20
    potrace_alphamax: float = 1.0
    potrace_opttolerance: float = 0.2
    curve_sample_tol_mm: float = 0.05
    kerf_mode: KerfMode = "app"
    # PROVISIONAL (specification, 17): glow compensation, confirmed by phase E.
    edge_inset_mm: dict[InputKind, float] = field(
        default_factory=lambda: {"mockup": 0.5, "photo": 0.8}
    )
    simplify_tol_mm: float = 0.03
    engrave_margin_mm: float = 1.5
    print_dpi: int = 600
    print_bleed_mm: float = 0.3
    registration_marks: bool = True
    svg_margin_mm: float = 5.0
    cut_stroke: str = "#FF0000"
    cut_stroke_width_mm: float = 0.1
    engrave_color: str = "#0000FF"
    # Implementation choices (not fixed by the specification):
    min_edge_mm: float = 0.02  # shortest allowed polygon edge (specification, 8.5)
    thin_feature_min_area_mm2: float = 0.5  # warning threshold for thin regions (8.5)
    vectorize_backend: VectorizeBackend = "potrace"
    vectorize_upsample_threshold_px: int = 1500  # PROVISIONAL: 2x bitmap below this
    min_resolution_px: int = 1000  # warn below this longer side (specification, 3)

    def __post_init__(self) -> None:
        if self.kerf_mode not in VALID_KERF_MODES:
            raise ValueError(f"kerf_mode must be one of {VALID_KERF_MODES}, got {self.kerf_mode!r}")
        if self.sam_variant not in VALID_SAM_VARIANTS:
            raise ValueError(f"unknown sam_variant {self.sam_variant!r}")
        if self.device not in VALID_DEVICES:
            raise ValueError(f"unknown device {self.device!r}")
        if self.vectorize_backend not in VALID_BACKENDS:
            raise ValueError(f"unknown vectorize_backend {self.vectorize_backend!r}")
        if self.max_side_px < 64:
            raise ValueError("max_side_px must be at least 64")
        if self.print_dpi <= 0:
            raise ValueError("print_dpi must be positive")
        if self.print_order not in ("cut_then_print", "print_then_cut"):
            raise ValueError(f"unknown print_order {self.print_order!r}")
        if self.slot_solidity_min <= 0 or self.slot_solidity_min > 1:
            raise ValueError("slot_solidity_min must be in (0, 1]")
        if not 0 <= self.slot_overlap_max <= 1:
            raise ValueError("slot_overlap_max must be in [0, 1]")
        if self.slot_min_area_mm2 <= 0:
            raise ValueError("slot_min_area_mm2 must be positive")
        for kind in VALID_INPUT_KINDS:
            if kind not in self.edge_inset_mm:
                raise ValueError(f"edge_inset_mm is missing the {kind!r} entry")
        for inset in self.edge_inset_mm.values():
            if inset < 0:
                raise ValueError("edge_inset_mm values must be non-negative")

    def edge_inset(self, input_kind: InputKind) -> float:
        """Glow compensation for the given input kind (specification, 8.2 step 2)."""
        if input_kind not in VALID_INPUT_KINDS:
            raise ValueError(f"unknown input_kind {input_kind!r}")
        return self.edge_inset_mm[input_kind]

    @classmethod
    def from_toml(cls, path: Path | str) -> Config:
        """Load a Config from a TOML file; unknown keys raise (strict configuration)."""
        path = Path(path)
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        return cls.from_mapping(data)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> Config:
        known = {item.name for item in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"unknown configuration keys: {', '.join(unknown)}")
        return cls(**data)


def default_config() -> Config:
    """Return the default configuration (specification, 6.1)."""
    return Config()
