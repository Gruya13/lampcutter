"""Kerf calibration (specification, 7.9).

`lampcutter calibrate` exports squares of *nominal* size, without kerf
compensation. The user cuts them, measures each square with a caliper and enters
the values; `kerf = nominal - measured` (averaged) goes into the material
profile. The same procedure validates the tab fit in the base slot.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import Polygon, box

from lampcutter.config import Config
from lampcutter.core import svg_writer

DEFAULT_SIZES_MM: tuple[float, ...] = (20.0, 30.0, 40.0)
DEFAULT_SPACING_MM = 10.0


@dataclass(frozen=True)
class KerfMeasurement:
    """One measured calibration square."""

    nominal_mm: float
    measured_mm: float

    @property
    def kerf_mm(self) -> float:
        return compute_kerf(self.nominal_mm, self.measured_mm)


def parse_sizes(value: str) -> list[float]:
    """Parse a comma separated list of nominal sizes in millimetres."""
    sizes: list[float] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            size = float(item)
        except ValueError as error:
            raise ValueError(f"neispravna veličina {item!r}; očekivan broj u mm") from error
        if size <= 0:
            raise ValueError("veličine kvadrata moraju biti pozitivne")
        sizes.append(size)
    if not sizes:
        raise ValueError("potrebna je bar jedna veličina kvadrata")
    return sizes


def calibration_squares(
    sizes_mm: list[float],
    spacing_mm: float = DEFAULT_SPACING_MM,
) -> list[Polygon]:
    """Lay out the calibration squares in one row with equal spacing."""
    if not sizes_mm:
        raise ValueError("potrebna je bar jedna veličina kvadrata")
    if spacing_mm < 0:
        raise ValueError("spacing_mm mora biti nenegativan")
    squares: list[Polygon] = []
    left = 0.0
    for size in sizes_mm:
        if size <= 0:
            raise ValueError("veličine kvadrata moraju biti pozitivne")
        squares.append(box(left, 0.0, left + size, size))
        left += size + spacing_mm
    return squares


def build_calibration_svg(
    sizes_mm: list[float],
    path: Path | str,
    config: Config | None = None,
    spacing_mm: float = DEFAULT_SPACING_MM,
) -> Path:
    """Write the calibration SVG: nominal squares, no kerf compensation."""
    cfg = config or Config()
    squares = calibration_squares(sizes_mm, spacing_mm)
    return svg_writer.write_polygons_svg(squares, path, cfg)


def compute_kerf(nominal_mm: float, measured_mm: float) -> float:
    """`kerf = nominal - measured` (specification, 7.9)."""
    if nominal_mm <= 0:
        raise ValueError("nominal_mm must be positive")
    if measured_mm <= 0:
        raise ValueError("measured_mm must be positive")
    return nominal_mm - measured_mm


def average_kerf(measurements: list[KerfMeasurement]) -> float:
    """Average kerf over several calibration squares."""
    if not measurements:
        raise ValueError("potrebno je bar jedno merenje")
    return sum(item.kerf_mm for item in measurements) / len(measurements)


def measurements_from_lists(
    sizes_mm: list[float],
    measured_mm: list[float],
) -> list[KerfMeasurement]:
    """Pair nominal and measured values; lengths must match."""
    if len(sizes_mm) != len(measured_mm):
        raise ValueError(
            f"broj nominalnih ({len(sizes_mm)}) i izmerenih ({len(measured_mm)}) "
            "vrednosti mora da se poklapa"
        )
    return [
        KerfMeasurement(nominal_mm=nominal, measured_mm=measured)
        for nominal, measured in zip(sizes_mm, measured_mm, strict=True)
    ]
