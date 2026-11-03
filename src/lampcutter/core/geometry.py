"""Cut geometry: glow inset, holes, simplification, thin features, kerf (spec, 8)."""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import shapely
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

from lampcutter.config import Config, InputKind, KerfMode
from lampcutter.models import BaseProfile, CutGeometry, MaterialProfile


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
    """Reduce a geometry to one valid polygon, keeping the largest part (spec, 7.6)."""
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
        if (
            not cleaned
            or ((cleaned[-1][0] - point[0]) ** 2 + (cleaned[-1][1] - point[1]) ** 2)
            >= min_edge_mm**2
        ):
            cleaned.append(point)
    while (
        len(cleaned) > 3
        and ((cleaned[0][0] - cleaned[-1][0]) ** 2 + (cleaned[0][1] - cleaned[-1][1]) ** 2)
        < min_edge_mm**2
    ):
        cleaned.pop()
    while (
        len(cleaned) > 3
        and ((cleaned[0][0] - cleaned[1][0]) ** 2 + (cleaned[0][1] - cleaned[1][1]) ** 2)
        < min_edge_mm**2
    ):
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


# --------------------------------------------------------------------- base tab
# Specification, section 8.3: tab, slot clearance and the kerf rule for the tab.

# PROVISIONAL (specification, 17): clearance thresholds are confirmed by the user.
MAX_PLANAR_CLEARANCE_MM = 1.0
MAX_THICKNESS_CLEARANCE_MM = 0.3
# PROVISIONAL: a smoothed mask edge is never perfectly straight; the bottom
# contact is the part of the outline within this distance from the lowest point.
BOTTOM_FLAT_TOLERANCE_MM = 0.2


class TabError(GeometryError):
    """The tab cannot be placed on the bottom contact of the outline."""


@dataclass(frozen=True)
class SlotClearance:
    """Fit of the tab in the base slot (specification, 8.3)."""

    effective_slot_length_mm: float
    planar_clearance_mm: float
    thickness_clearance_mm: float
    warnings: tuple[str, ...]


def bottom_contact(
    polygon: shapely.Geometry,
    flat_tolerance_mm: float = BOTTOM_FLAT_TOLERANCE_MM,
) -> tuple[float, float, float]:
    """Return `(min_x, max_x, y_bottom)` of the bottom contact line.

    A Gaussian-smoothed mask edge is never perfectly straight, so the contact is
    the stretch of the outline within `flat_tolerance_mm` of the lowest point.
    Raises `TabError` when there is no flat stretch (a pointed bottom); the user
    is expected to cut it straight with `mask_ops.cut_at_line` (specification 7.4).
    """
    if flat_tolerance_mm <= 0:
        raise ValueError("flat_tolerance_mm must be positive")
    candidate = ensure_valid(polygon)
    coords = list(candidate.exterior.coords)
    y_bottom = max(y for _, y in coords)
    contact_xs = [x for x, y in coords if y >= y_bottom - flat_tolerance_mm]
    if len(contact_xs) < 2 or max(contact_xs) - min(contact_xs) <= 1e-6:
        raise TabError("donja ivica nije ravna; iseci je na liniju postolja pre dodavanja jezička")
    return (min(contact_xs), max(contact_xs), y_bottom)


def _rounded_rectangle(
    width: float,
    height: float,
    radius: float,
    center_x: float,
    top_y: float,
) -> Polygon:
    """A rectangle with rounded corners, top edge at `top_y`, centred on `center_x`."""
    corner = max(0.0, min(radius, width / 2.0, height / 2.0))
    left = center_x - width / 2.0
    right = center_x + width / 2.0
    if corner <= 0.0:
        return Polygon(
            [(left, top_y), (right, top_y), (right, top_y + height), (left, top_y + height)]
        )
    inner = Polygon(
        [
            (left + corner, top_y + corner),
            (right - corner, top_y + corner),
            (right - corner, top_y + height - corner),
            (left + corner, top_y + height - corner),
        ]
    )
    return ensure_valid(inner.buffer(corner, join_style="round", quad_segs=32))


def add_tab(nominal: shapely.Geometry, base: BaseProfile) -> Polygon:
    """Union the lamp body with the base tab (specification, 8.3).

    The tab is a rounded rectangle `tab_width_mm + tab_fit_mm` wide and
    `tab_height_mm` deep, centred on the bottom contact plus `tab_offset_mm`.
    `tab_fit_mm` is applied to the tab only; it never changes the body.
    """
    body = ensure_valid(nominal)
    width = base.tab_width_mm + base.tab_fit_mm
    if width <= 0:
        raise TabError(f"jezičak mora imati pozitivnu širinu (dobijeno {width:.3f} mm)")
    if base.tab_height_mm <= 0:
        raise TabError("tab_height_mm mora biti pozitivna")
    min_x, max_x, y_bottom = bottom_contact(body)
    contact_length = max_x - min_x
    if width > contact_length + 1e-9:
        raise TabError(
            f"jezičak ({width:.2f} mm) je širi od donjeg kontakta ({contact_length:.2f} mm)"
        )
    center_x = (min_x + max_x) / 2.0 + base.tab_offset_mm
    overlap = min(0.2, base.tab_height_mm / 2.0)  # tiny overlap so the union is clean
    tab = _rounded_rectangle(
        width,
        base.tab_height_mm + overlap,
        base.corner_radius_mm,
        center_x,
        y_bottom - overlap,
    )
    return ensure_valid(shapely.union(body, tab))


def effective_slot_length(base: BaseProfile) -> float:
    """Slot length in the plate plane, after base kerf when the base is laser cut."""
    if base.slot_dimensions == "nominal_laser_cut":
        return base.slot_length_mm + base.base_kerf_mm
    return base.slot_length_mm


def slot_clearance(base: BaseProfile, material: MaterialProfile) -> SlotClearance:
    """Planar and thickness clearance between the tab and the base slot (8.3)."""
    effective = effective_slot_length(base)
    planar = effective - (base.tab_width_mm + base.tab_fit_mm)
    thickness = base.slot_thickness_mm - material.thickness_mm
    warnings: list[str] = []
    if thickness < 0:
        warnings.append(
            f"materijal je deblji od proreza ({material.thickness_mm:.2f} > "
            f"{base.slot_thickness_mm:.2f} mm) — neće ući"
        )
    elif thickness > MAX_THICKNESS_CLEARANCE_MM:
        warnings.append(f"prevelik zazor po debljini ({thickness:.2f} mm) — jezičak će se klimati")
    if planar < 0:
        warnings.append(
            f"jezičak je širi od proreza ({base.tab_width_mm + base.tab_fit_mm:.2f} > "
            f"{effective:.2f} mm) — neće ući"
        )
    elif planar > MAX_PLANAR_CLEARANCE_MM:
        warnings.append(f"prevelik zazor u ravni ({planar:.2f} mm) — jezičak će se klimati")
    return SlotClearance(
        effective_slot_length_mm=effective,
        planar_clearance_mm=planar,
        thickness_clearance_mm=thickness,
        warnings=tuple(warnings),
    )


def prepare_nominal(
    polygon: shapely.Geometry,
    config: Config,
    input_kind: InputKind,
    base: BaseProfile | None = None,
) -> Polygon:
    """Run specification 8.2 steps 1-6; step 4 adds the tab when a base is given."""
    result = ensure_valid(polygon)
    result = apply_edge_inset(result, config.edge_inset(input_kind))
    result = fill_holes(result)
    if base is not None:
        result = add_tab(result, base)
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
