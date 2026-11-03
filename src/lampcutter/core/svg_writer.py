"""LightBurn-compatible SVG writer (specification, 7.8 and 9.4).

The coordinate origin is the top-left corner of the NOMINAL geometry plus
`svg_margin_mm`. The cut path is translated against that same origin, never
against its own (larger) bounding box, so print and cut share one reference.
"""

from __future__ import annotations

import base64
import io
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image
from shapely.geometry import Polygon

from lampcutter.config import Config
from lampcutter.models import CutGeometry

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
SVG_DECIMALS = 3


def _fmt(value: float) -> str:
    return f"{value:.{SVG_DECIMALS}f}"


def polygon_path_data(
    polygon: Polygon,
    dx: float = 0.0,
    dy: float = 0.0,
) -> str:
    """Convert a polygon exterior ring into an absolute SVG path (M/L/Z)."""
    if polygon.is_empty:
        raise ValueError("empty polygon")
    coords = list(polygon.exterior.coords)
    if len(coords) < 3:
        raise ValueError("polygon ring has fewer than 3 points")
    commands = [f"M {_fmt(coords[0][0] + dx)} {_fmt(coords[0][1] + dy)}"]
    commands.extend(f"L {_fmt(x + dx)} {_fmt(y + dy)}" for x, y in coords[1:])
    commands.append("Z")
    return " ".join(commands)


def canvas_size_mm(geometry: CutGeometry, config: Config) -> tuple[float, float]:
    """Canvas dimensions: nominal bounding box plus the margin on both sides."""
    min_x, min_y, max_x, max_y = geometry.bbox_nominal_mm
    margin = 2.0 * config.svg_margin_mm
    return (max_x - min_x + margin, max_y - min_y + margin)


def origin_offset_mm(geometry: CutGeometry, config: Config) -> tuple[float, float]:
    """Translation that puts the nominal top-left corner at (margin, margin)."""
    min_x, min_y, _, _ = geometry.bbox_nominal_mm
    margin = config.svg_margin_mm
    return (margin - min_x, margin - min_y)


def build_svg(
    geometry: CutGeometry,
    config: Config,
    engrave: list[Polygon] | None = None,
) -> ET.ElementTree:
    """Build the SVG tree; cut and engrave live in separate, coloured layers."""
    width_mm, height_mm = canvas_size_mm(geometry, config)
    dx, dy = origin_offset_mm(geometry, config)
    root = ET.Element(
        "svg",
        {
            "xmlns": SVG_NAMESPACE,
            "width": f"{_fmt(width_mm)}mm",
            "height": f"{_fmt(height_mm)}mm",
            "viewBox": f"0 0 {_fmt(width_mm)} {_fmt(height_mm)}",
        },
    )
    cut_group = ET.SubElement(
        root,
        "g",
        {
            "id": "cut-outer",
            "fill": "none",
            "stroke": config.cut_stroke,
            "stroke-width": _fmt(config.cut_stroke_width_mm),
        },
    )
    ET.SubElement(cut_group, "path", {"d": polygon_path_data(geometry.cut_path, dx, dy)})
    if engrave:
        engrave_group = ET.SubElement(
            root,
            "g",
            {
                "id": "engrave",
                "fill": config.engrave_color,
                "stroke": config.engrave_color,
                "stroke-width": _fmt(config.cut_stroke_width_mm),
            },
        )
        for polygon in engrave:
            ET.SubElement(engrave_group, "path", {"d": polygon_path_data(polygon, dx, dy)})
    return ET.ElementTree(root)


def write_cut_svg(
    geometry: CutGeometry,
    path: Path | str,
    config: Config,
    engrave: list[Polygon] | None = None,
) -> Path:
    """Write the cut/engrave SVG and validate its reloaded dimensions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = build_svg(geometry, config, engrave)
    ET.register_namespace("", SVG_NAMESPACE)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    expected_width, expected_height = canvas_size_mm(geometry, config)
    validate_svg(path, expected_width, expected_height)
    return path


def _bounds_mm(polygons: list[Polygon]) -> tuple[float, float, float, float]:
    if not polygons:
        raise ValueError("nema poligona")
    bounds = [polygon.bounds for polygon in polygons]
    return (
        min(item[0] for item in bounds),
        min(item[1] for item in bounds),
        max(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )


def write_polygons_svg(
    polygons: list[Polygon],
    path: Path | str,
    config: Config,
    stroke: str | None = None,
) -> Path:
    """Write several polygons as one cut layer (used by the calibration sheet)."""
    if not polygons:
        raise ValueError("nema poligona")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    min_x, min_y, max_x, max_y = _bounds_mm(polygons)
    margin = config.svg_margin_mm
    width_mm = max_x - min_x + 2 * margin
    height_mm = max_y - min_y + 2 * margin
    dx = margin - min_x
    dy = margin - min_y
    root = ET.Element(
        "svg",
        {
            "xmlns": SVG_NAMESPACE,
            "width": f"{_fmt(width_mm)}mm",
            "height": f"{_fmt(height_mm)}mm",
            "viewBox": f"0 0 {_fmt(width_mm)} {_fmt(height_mm)}",
        },
    )
    group = ET.SubElement(
        root,
        "g",
        {
            "id": "cut-outer",
            "fill": "none",
            "stroke": stroke or config.cut_stroke,
            "stroke-width": _fmt(config.cut_stroke_width_mm),
        },
    )
    for polygon in polygons:
        ET.SubElement(group, "path", {"d": polygon_path_data(polygon, dx, dy)})
    ET.register_namespace("", SVG_NAMESPACE)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    validate_svg(path, width_mm, height_mm)
    return path


def read_svg_size_mm(path: Path | str) -> tuple[float, float]:
    """Read the width and height of an SVG in millimetres."""
    root = ET.parse(Path(path)).getroot()
    width = root.get("width", "")
    height = root.get("height", "")
    if not width.endswith("mm") or not height.endswith("mm"):
        raise ValueError("SVG width/height must be millimetres")
    return (float(width[:-2]), float(height[:-2]))


def validate_svg(
    path: Path | str,
    expected_width_mm: float,
    expected_height_mm: float,
    tolerance_mm: float = 1e-3,
) -> None:
    """Reload the SVG and check that its declared size matches the expectation."""
    width_mm, height_mm = read_svg_size_mm(path)
    if abs(width_mm - expected_width_mm) > tolerance_mm:
        raise ValueError(f"SVG width {width_mm} mm != expected {expected_width_mm} mm")
    if abs(height_mm - expected_height_mm) > tolerance_mm:
        raise ValueError(f"SVG height {height_mm} mm != expected {expected_height_mm} mm")


def write_preview_svg(
    image: Image.Image,
    polygons_px: list[Polygon],
    path: Path | str,
    stroke: str = "#00AA00",
) -> Path:
    """Debug preview: the source image with contours drawn over it, in pixels."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    width, height = image.size
    root = ET.Element(
        "svg",
        {
            "xmlns": SVG_NAMESPACE,
            "width": f"{width}px",
            "height": f"{height}px",
            "viewBox": f"0 0 {width} {height}",
        },
    )
    ET.SubElement(
        root,
        "image",
        {"href": f"data:image/png;base64,{encoded}", "width": str(width), "height": str(height)},
    )
    group = ET.SubElement(root, "g", {"fill": "none", "stroke": stroke, "stroke-width": "1"})
    for polygon in polygons_px:
        ET.SubElement(group, "path", {"d": polygon_path_data(polygon)})
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path
