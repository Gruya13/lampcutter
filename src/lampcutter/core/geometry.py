"""Cut geometry: glow inset, holes, simplification, thin features, kerf (spec, 8)."""

from __future__ import annotations

import warnings
from collections.abc import Sequence

import shapely
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

from lampcutter.config import Config, InputKind, KerfMode
from lampcutter.models import CutGeometry, MaterialProfile


class GeometryError(ValueError):
    """The geometry cannot be turned into a laser-ready contour."""


class ThinFeatureWarning(UserWarning):
    """Part of the outline is thinner than the material allows (specification, 8.5)."""


def largest_polygon(geometry: shapely.Geometry) -> Polygon:
    """Return the largest Polygon inside any shapely geometry."""
    if isinstance(geometry, Polygon):
        return geometry
    if isinstance(geometry, (MultiPolygon, GeometryCollection)):
        polygons = [part for part in shapely.get_parts(geometry) if isinstance(part, Polygon)]
        if not polygons:
            raise GeometryError("geometrija ne sadrži nijedan poligon")
        return max(polygons, key=lambda item: item.area)
    raise GeometryError(f"očekivan je poligon, dobijeno: {geometry.geom_type}")


def ensure_valid(polygon: shapely.Geometry) -> Polygon:
    """Make a geometry valid and reduce it to its largest polygon (specification, 7.6)."""
    candidate = polygon
    if not candidate.is_valid:
        candidate = shapely.make_valid(candidate)
    result = largest_polygon(candidate)
    if result.is_empty or result.area <= 0:
        raise GeometryError("kontura je prazna nakon validacije")
    return result


def ensure_single_polygon(polygon: shapely.Geometry) -> Polygon:
    """Return the largest polygon; raise if the geometry contains several parts."""
    if isinstance(polygon, MultiPolygon) and len(polygon.geoms) > 1:
        raise GeometryError("kontura mora biti jedan poligon (specifikacija, 8.4)")
    return ensure_valid(polygon)


def fill_holes(polygon: shapely.Geometry) -> Polygon:
    """Drop all interior holes: v1 cuts only the outer contour (specification, 8.2)."""
    candidate = ensure_valid(polygon)
    return Polygon(candidate.exterior)


def apply_edge_inset(polygon: shapely.Geometry, inset_mm: float) -> Polygon:
    """Shrink by the glow compensation distance (specification, 8.2 step 2)."""
    if inset_mm < 0:
        raise ValueError("inset_mm must be non-negative")
    candidate = ensure_valid(polygon)
    if inset_mm == 0:
        return candidate
    inset = candidate.buffer(-inset_mm)
    if inset.is_empty:
        raise GeometryError(f"kontura nestaje pri uvlačenju od {inset_mm} mm")
    return ensure_valid(inset)


def simplify(polygon: shapely.Geometry, tolerance_mm: float) -> Polygon:
    """Topology-preserving simplification before the kerf offset (specification, 8.2 step 5)."""
    if tolerance_mm < 0:
        raise ValueError("tolerance_mm must be non-negative")
    candidate = ensure_valid(polygon)
    if tolerance_mm == 0:
        return candidate
    return ensure_valid(candidate.simplify(tolerance_mm, preserve_topology=True))


def clean_ring(
    points: Sequence[tuple[float, float]],
    min_edge_mm: float,
) -> list[tuple[float, float]]:
    """Drop consecutive vertices closer than `min_edge_mm` (specification, 8.5)."""
    if min_edge_mm <= 0:
        return list(points)
    cleaned: list[tuple[float, float]] = []
    for point in points:
        if not cleaned or (
            (cleaned[-1][0] - point[0]) ** 2 + (cleaned[-1][1] - point[1]) ** 2
        ) >= min_edge_mm**2:
            cleaned.append(point)
    while len(cleaned) > 3 and (
        (cleaned[0][0] - cleaned[-1][0]) ** 2 + (cleaned[0][1] - cleaned[-1][1]) ** 2
    ) < min_edge_mm**2:
        cleaned.pop()
    while len(cleaned) > 3 and (
        (cleaned[0][0] - cleaned[1][0]) ** 2 + (cleaned[0][1] - cleaned[1][1]) ** 2
    ) < min_edge_mm**2:
        cleaned.pop(0)
    return cleaned


def clean_polygon_edges(polygon: shapely.Geometry, min_edge_mm: float) -> Polygon:
    """Remove edges shorter than `min_edge_mm` from the exterior ring."""
    candidate = ensure_valid(polygon)
    ring = clean_ring(list(candidate.exterior.coords)[:-1], min_edge_mm)
    if len(ring) < 3:
        raise GeometryError("kontura ima manje od 3 tačke nakon uklanjanja kratkih ivica")
    return ensure_valid(Polygon(ring))


def find_thin_regions(polygon: shapely.Geometry, min_feature_mm: float) -> shapely.Geometry:
    """Return the geometry thinner than `min_feature_mm` (specification, 8.5).

    A morphology opening with a disc of diameter `min_feature_mm` removes
    features thinner than that; whatever disappears is returned.
    """
    if min_feature_mm <= 0:
        raise ValueError("min_feature_mm must be positive")
    candidate = ensure_valid(polygon)
    radius = min_feature_mm / 2.0
    opened = candidate.buffer(-radius).buffer(radius)
    if opened.is_empty:
        return candidate
    return candidate.difference(opened)


def check_min_feature(
    polygon: shapely.Geometry,
    min_feature_mm: float,
    warn: bool = True,
    min_area_mm2: float = 0.5,
) -> shapely.Geometry:
    """Detect thin material; warn with `ThinFeatureWarning` unless disabled.

    `min_area_mm2` filters out sharp corners that a morphology opening always
    nibbles away; only material loss above this area is reported.
    """
    thin = find_thin_regions(polygon, min_feature_mm)
    if warn and not thin.is_empty and thin.area > min_area_mm2:
        warnings.warn(
            f"Kontura ima delove tanje od {min_feature_mm} mm "
            f"({thin.area:.2f} mm²). Proveri mesto pre sečenja.",
            ThinFeatureWarning,
            stacklevel=2,
        )
    return thin


def apply_kerf(
    nominal: shapely.Geometry,
    kerf_mm: float,
    kerf_mode: KerfMode = "app",
) -> Polygon:
    """Offset the nominal contour outwards by `kerf/2` (specification, 8.1 and 8.2).

    With `kerf_mode="lightburn"` the nominal contour is exported unchanged and
    LightBurn performs the compensation itself.
    """
    if kerf_mm < 0:
        raise ValueError("kerf_mm must be non-negative")
    candidate = ensure_valid(nominal)
    if kerf_mode == "lightburn":
        return candidate
    if kerf_mode != "app":
        raise ValueError(f"unknown kerf_mode {kerf_mode!r}")
    if kerf_mm == 0:
        return candidate
    return ensure_valid(candidate.buffer(kerf_mm / 2.0, join_style="round", quad_segs=32))


def prepare_nominal(
    polygon: shapely.Geometry,
    config: Config,
    input_kind: InputKind,
) -> Polygon:
    """Run specification 8.2 steps 1-6, without the tab (phase 0a)."""
    result = ensure_valid(polygon)
    result = apply_edge_inset(result, config.edge_inset(input_kind))
    result = fill_holes(result)
    result = simplify(result, config.simplify_tol_mm)
    result = clean_polygon_edges(result, config.min_edge_mm)
    return ensure_valid(result)


def compute_cut_geometry(
    nominal: shapely.Geometry,
    material: MaterialProfile,
    kerf_mode: KerfMode = "app",
    min_edge_mm: float = 0.02,
) -> CutGeometry:
    """Return the nominal geometry and its kerf-compensated cut path (specification, 8.1).

    The kerf buffer introduces a dense fan of points on every corner; edges
    shorter than `min_edge_mm` are removed so LightBurn does not receive
    micro-segments (specification, 8.5).
    """
    nominal_polygon = ensure_valid(nominal)
    cut_path = apply_kerf(nominal_polygon, material.kerf_mm, kerf_mode)
    cut_path = clean_polygon_edges(cut_path, min_edge_mm)
    return CutGeometry(
        nominal=nominal_polygon,
        cut_path=cut_path,
        kerf_mm=material.kerf_mm,
        area_mm2=float(nominal_polygon.area),
        bbox_nominal_mm=tuple(float(value) for value in nominal_polygon.bounds),  # type: ignore[arg-type]
    )
