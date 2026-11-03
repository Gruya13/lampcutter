"""Photo slots and .lamptpl serialisation (specification, 5, 9.1, 9.2, 9.4).

The template is JSON with all shapely geometry as **GeoJSON** and coordinates
rounded to 0.001 mm. Validations live here too: the "runaway click" check for a
slot mask and the fit/overlap checks used by the GUI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Polygon, mapping, shape

from lampcutter.config import Config
from lampcutter.models import (
    BaseProfile,
    CutGeometry,
    DecorElement,
    LampTemplate,
    MaterialProfile,
    PhotoSlot,
    ScaleInfo,
)

SCHEMA_VERSION = 1
ROUND_MM = 0.001


def round_polygon(polygon: shapely.Geometry, decimals: int = 3) -> shapely.Geometry:
    """Round every coordinate to `decimals` (0.001 mm by default)."""
    data = mapping(polygon)
    return shape(_round_coordinates(data, decimals))


def _round_coordinates(node: Any, decimals: int) -> Any:
    if isinstance(node, (int, float)):
        return round(float(node), decimals)
    if isinstance(node, (list, tuple)):
        return [_round_coordinates(item, decimals) for item in node]
    if isinstance(node, dict):
        return {key: _round_coordinates(value, decimals) for key, value in node.items()}
    return node


def polygon_to_geojson(polygon: shapely.Geometry, decimals: int = 3) -> dict:
    """GeoJSON geometry with rounded coordinates (`schema: 1` convention)."""
    return _round_coordinates(mapping(polygon), decimals)


def polygon_from_geojson(data: dict) -> Polygon:
    """Rebuild a polygon from GeoJSON; keeps the largest part of a multi-part."""
    geometry = shape(data)
    if isinstance(geometry, MultiPolygon):
        return max(geometry.geoms, key=lambda item: item.area)
    if isinstance(geometry, Polygon):
        return geometry
    raise ValueError(f"očekivan je poligon, dobijeno: {geometry.geom_type}")


def _profile_dict(item: MaterialProfile | BaseProfile) -> dict:
    return {name: value for name, value in item.__dict__.items()}


def scale_to_geojson(scale: ScaleInfo) -> dict:
    return {
        "mm_per_px": scale.mm_per_px,
        "reference": scale.reference,
        "reference_mm": scale.reference_mm,
        "bbox_px": list(scale.bbox_px),
    }


def scale_from_geojson(data: dict) -> ScaleInfo:
    return ScaleInfo(
        mm_per_px=float(data["mm_per_px"]),
        reference=data["reference"],
        reference_mm=float(data["reference_mm"]),
        bbox_px=tuple(int(value) for value in data["bbox_px"]),
    )


def cut_geometry_to_geojson(cut_geometry: CutGeometry) -> dict:
    return {
        "nominal": polygon_to_geojson(cut_geometry.nominal),
        "cut_path": polygon_to_geojson(cut_geometry.cut_path),
        "kerf_mm": cut_geometry.kerf_mm,
        "area_mm2": cut_geometry.area_mm2,
        "bbox_nominal_mm": list(cut_geometry.bbox_nominal_mm),
    }


def cut_geometry_from_geojson(data: dict) -> CutGeometry:
    return CutGeometry(
        nominal=polygon_from_geojson(data["nominal"]),
        cut_path=polygon_from_geojson(data["cut_path"]),
        kerf_mm=float(data["kerf_mm"]),
        area_mm2=float(data["area_mm2"]),
        bbox_nominal_mm=tuple(float(value) for value in data["bbox_nominal_mm"]),
    )


def slot_to_geojson(slot: PhotoSlot) -> dict:
    return {
        "id": slot.id,
        "polygon_mm": polygon_to_geojson(slot.polygon_mm),
        "source": slot.source,
        "image_path": str(slot.image_path) if slot.image_path is not None else None,
        "fit": slot.fit,
        "zoom": slot.zoom,
        "offset_mm": list(slot.offset_mm),
        "rotation_deg": slot.rotation_deg,
        "bleed_mm": slot.bleed_mm,
    }


def slot_from_geojson(data: dict) -> PhotoSlot:
    image_path = data.get("image_path")
    return PhotoSlot(
        id=str(data["id"]),
        polygon_mm=polygon_from_geojson(data["polygon_mm"]),
        source=data.get("source", "manual"),
        image_path=Path(image_path) if image_path else None,
        fit=data.get("fit", "cover"),
        zoom=float(data.get("zoom", 1.0)),
        offset_mm=tuple(float(value) for value in data.get("offset_mm", (0.0, 0.0))),
        rotation_deg=float(data.get("rotation_deg", 0.0)),
        bleed_mm=data.get("bleed_mm"),
    )


def decor_to_geojson(element: DecorElement) -> dict:
    return {
        "id": element.id,
        "polygon_mm": polygon_to_geojson(element.polygon_mm),
        "source": element.source,
        "mode": element.mode,
        "engrave_style": element.engrave_style,
        "color_override": element.color_override,
    }


def decor_from_geojson(data: dict) -> DecorElement:
    return DecorElement(
        id=str(data["id"]),
        polygon_mm=polygon_from_geojson(data["polygon_mm"]),
        source=data.get("source", "threshold"),
        mode=data.get("mode", "engrave"),
        engrave_style=data.get("engrave_style", "fill"),
        color_override=data.get("color_override"),
    )


def template_to_geojson(template: LampTemplate) -> dict:
    """Full template as JSON-ready data (`.lamptpl`, specification 5 and 9.2)."""
    return {
        "schema": SCHEMA_VERSION,
        "outline": cut_geometry_to_geojson(template.outline),
        "slots": [slot_to_geojson(slot) for slot in template.slots],
        "decor": [decor_to_geojson(element) for element in template.decor],
        "base": _profile_dict(template.base),
        "material": _profile_dict(template.material),
        "scale": scale_to_geojson(template.scale),
        "input_kind": template.input_kind,
    }


def template_from_geojson(data: dict) -> LampTemplate:
    if int(data.get("schema", 0)) != SCHEMA_VERSION:
        raise ValueError(f"nepoznata verzija šeme šablona: {data.get('schema')!r}")
    return LampTemplate(
        outline=cut_geometry_from_geojson(data["outline"]),
        slots=[slot_from_geojson(item) for item in data.get("slots", [])],
        decor=[decor_from_geojson(item) for item in data.get("decor", [])],
        base=BaseProfile(**_profile_dict_shape(data["base"])),
        material=MaterialProfile(**_profile_dict_shape(data["material"])),
        scale=scale_from_geojson(data["scale"]),
        input_kind=data.get("input_kind", "mockup"),
    )


def _profile_dict_shape(data: dict) -> dict:
    """Drop keys that the dataclass does not accept (forward compatibility)."""
    return dict(data)


def save_template(template: LampTemplate, path: Path | str) -> Path:
    """Write a `.lamptpl` JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(template_to_geojson(template), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_template(path: Path | str) -> LampTemplate:
    """Read a `.lamptpl` JSON file."""
    return template_from_geojson(json.loads(Path(path).read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Slot validation ("runaway click" check, specification 7.3 and 8.4)


def validate_slot_mask(
    mask: np.ndarray,
    mm_per_px: float,
    existing_slots: list[shapely.Geometry] | None = None,
    config: Config | None = None,
) -> list[str]:
    """Report problems with a slot candidate mask: area, solidity, overlap.

    Returns a list of human readable warnings; an empty list means the candidate
    passed the "runaway click" checks.
    """
    cfg = config or Config()
    binary = mask.astype(bool, copy=False)
    if binary.ndim != 2:
        raise ValueError("mask must be a 2-D array")
    if not binary.any():
        return ["maska je prazna"]
    warnings: list[str] = []
    area_mm2 = float(binary.sum()) * mm_per_px**2
    if area_mm2 < cfg.slot_min_area_mm2:
        warnings.append(
            f"slot je premali — površina {area_mm2:.1f} mm² je ispod "
            f"{cfg.slot_min_area_mm2:.0f} mm²; moguće da je klik promašio"
        )
    contours, _ = _contours(binary)
    solidity = 1.0
    if contours:
        contour_area = float(max(_contour_area(contour) for contour in contours))
        if contour_area > 0:
            solidity = area_mm2 / (contour_area * mm_per_px**2)
    if solidity < cfg.slot_solidity_min:
        warnings.append(
            f"slot je raskomadan (solidnost {solidity:.2f}); probaj negativne tačke "
            "ili ručni poligon"
        )
    if existing_slots:
        new_area = max(area_mm2, 1e-9)
        candidate = _mask_to_polygon(binary)
        if candidate is not None:
            for index, existing in enumerate(existing_slots):
                # Accept either bare shapely polygons or PhotoSlot objects.
                existing_polygon = getattr(existing, "polygon_mm", existing)
                intersection = candidate.intersection(existing_polygon).area
                if intersection / new_area > cfg.slot_overlap_max:
                    warnings.append(
                        f"slot # {index + 1} se previše preklapa sa novim slotom "
                        f"({100 * intersection / new_area:.0f}%)"
                    )
    return warnings


def _contours(mask: np.ndarray):
    import cv2

    return cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)


def _contour_area(contour) -> float:
    import cv2

    return float(cv2.contourArea(contour))


def _mask_to_polygon(mask: np.ndarray, mm_per_px: float = 1.0) -> Polygon | None:
    from lampcutter.core.vectorize import contour_to_mm

    contours, _ = _contours(mask)
    if not contours:
        return None
    points = [(float(x), float(y)) for x, y in max(contours, key=_contour_area).reshape(-1, 2)]
    if len(points) < 3:
        return None
    return contour_to_mm(points, mm_per_px)
