"""Photo slots, print sheet and the export bundle (specification, 9.1-9.4).

Cut and print share one coordinate origin: the top-left corner of the NOMINAL
outline plus `svg_margin_mm`. The cut SVG translates the cut path against that
origin; the print sheet uses the same translation, which is what makes the two
line up (specification, 9.4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw

from lampcutter import __version__
from lampcutter.config import Config
from lampcutter.core import decor as decor_module
from lampcutter.core import io_utils, svg_writer
from lampcutter.core import slots as slots_module
from lampcutter.models import DecorElement, LampTemplate, PhotoSlot

MM_PER_INCH = 25.4


def mm_to_px(mm: float, dpi: float) -> float:
    """Millimetres to pixels at the given DPI."""
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    return mm / MM_PER_INCH * dpi


def px_to_mm(px: float, dpi: float) -> float:
    """Pixels to millimetres at the given DPI."""
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    return px * MM_PER_INCH / dpi


# --------------------------------------------------------------------- layout
def sheet_size_mm(template: LampTemplate, config: Config | None = None) -> tuple[float, float]:
    """Print sheet size: nominal bounding box plus the margin on both sides."""
    cfg = config or Config()
    min_x, min_y, max_x, max_y = template.outline.bbox_nominal_mm
    margin = 2.0 * cfg.svg_margin_mm
    return (max_x - min_x + margin, max_y - min_y + margin)


def sheet_offset_mm(template: LampTemplate, config: Config | None = None) -> tuple[float, float]:
    """Translation from lamp coordinates to sheet coordinates (same as in the SVG)."""
    cfg = config or Config()
    min_x, min_y, _, _ = template.outline.bbox_nominal_mm
    margin = cfg.svg_margin_mm
    return (margin - min_x, margin - min_y)


def registration_mark_positions(
    width_mm: float,
    height_mm: float,
    config: Config | None = None,
) -> list[tuple[float, float]]:
    """Four registration mark centres, one per sheet corner, in sheet millimetres."""
    cfg = config or Config()
    offset = cfg.registration_mark_offset_mm
    return [
        (offset, offset),
        (width_mm - offset, offset),
        (offset, height_mm - offset),
        (width_mm - offset, height_mm - offset),
    ]


def slot_bleed_mm(slot: PhotoSlot, config: Config | None = None) -> float:
    """Bleed used for one `photo_XX.png` (per slot, else the config default)."""
    if slot.bleed_mm is not None:
        return float(slot.bleed_mm)
    return (config or Config()).print_bleed_mm


def slot_bbox_mm(
    slot: PhotoSlot,
    config: Config | None = None,
    bleed: bool = False,
) -> tuple[float, float, float, float]:
    """Axis-aligned bounding box of a slot, optionally grown by the bleed."""
    polygon = slot.polygon_mm
    if bleed:
        polygon = polygon.buffer(slot_bleed_mm(slot, config))
    return tuple(float(value) for value in polygon.bounds)  # type: ignore[return-value]


def slot_px_size(
    slot: PhotoSlot,
    dpi: float,
    config: Config | None = None,
    bleed: bool = False,
) -> tuple[int, int]:
    """Pixel size of a slot image at `dpi` (at least 1x1)."""
    min_x, min_y, max_x, max_y = slot_bbox_mm(slot, config, bleed)
    return (
        max(1, round(mm_to_px(max_x - min_x, dpi))),
        max(1, round(mm_to_px(max_y - min_y, dpi))),
    )


def slot_alpha(
    slot: PhotoSlot,
    dpi: float,
    config: Config | None = None,
) -> Image.Image:
    """Boolean alpha mask of the slot shape at `dpi` (with bleed)."""
    cfg = config or Config()
    min_x, min_y, _, _ = slot_bbox_mm(slot, cfg, bleed=True)
    width_px, height_px = slot_px_size(slot, dpi, cfg, bleed=True)
    mask = Image.new("L", (width_px, height_px), 0)
    draw = ImageDraw.Draw(mask)
    points = [
        (
            mm_to_px(x - min_x, dpi),
            mm_to_px(y - min_y, dpi),
        )
        for x, y in slot.polygon_mm.exterior.coords
    ]
    draw.polygon(points, fill=255)
    return mask


# ------------------------------------------------------------------ photo fit
def fit_photo(
    photo: Image.Image,
    target_size: tuple[int, int],
    fit: str = "cover",
    zoom: float = 1.0,
    offset_mm: tuple[float, float] = (0.0, 0.0),
    rotation_deg: float = 0.0,
    dpi: float = 25.4,
) -> Image.Image:
    """Scale/crop a photo into the target slot box (cover or contain, pan/zoom/rotate)."""
    if fit not in ("cover", "contain"):
        raise ValueError(f"unknown fit {fit!r}")
    if zoom <= 0:
        raise ValueError("zoom must be positive")
    source = photo.convert("RGBA")
    target_w, target_h = target_size
    source_w, source_h = source.size
    if source_w <= 0 or source_h <= 0:
        raise ValueError("fotografija je prazna")
    if fit == "cover":
        scale = max(target_w / source_w, target_h / source_h)
    else:
        scale = min(target_w / source_w, target_h / source_h)
    scale *= zoom
    new_size = (max(1, round(source_w * scale)), max(1, round(source_h * scale)))
    resized = source.resize(new_size, Image.Resampling.LANCZOS)
    if rotation_deg:
        resized = resized.rotate(rotation_deg, expand=True, resample=Image.Resampling.BICUBIC)
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    offset_x = round(mm_to_px(offset_mm[0], dpi))
    offset_y = round(mm_to_px(offset_mm[1], dpi))
    paste_x = (target_w - resized.width) // 2 + offset_x
    paste_y = (target_h - resized.height) // 2 + offset_y
    canvas.paste(resized, (paste_x, paste_y), resized)
    return canvas


def effective_dpi(
    slot: PhotoSlot,
    photo_size: tuple[int, int],
    config: Config | None = None,
) -> float:
    """Effective print DPI of the photo inside the slot (warns below 150, spec 9.1)."""
    cfg = config or Config()
    min_x, min_y, max_x, max_y = slot_bbox_mm(slot, cfg, bleed=False)
    width_mm = max_x - min_x
    height_mm = max_y - min_y
    if width_mm <= 0 or height_mm <= 0:
        return 0.0
    source_w, source_h = photo_size
    target_w = mm_to_px(width_mm, cfg.print_dpi)
    target_h = mm_to_px(height_mm, cfg.print_dpi)
    if slot.fit == "cover":
        scale = max(target_w / source_w, target_h / source_h)
    else:
        scale = min(target_w / source_w, target_h / source_h)
    scale *= max(slot.zoom, 1e-9)
    used_px = target_w / scale
    return used_px / (width_mm / MM_PER_INCH)


def render_photo_slot(
    slot: PhotoSlot,
    config: Config | None = None,
    dpi: float | None = None,
) -> tuple[Image.Image, float]:
    """Render one `photo_XX.png` (RGBA slot shape, bleed) and its effective DPI."""
    cfg = config or Config()
    if slot.image_path is None:
        raise ValueError(f"slot '{slot.id}' nema fotografiju")
    output_dpi = dpi if dpi is not None else cfg.print_dpi
    photo = io_utils.load_image(slot.image_path, min_resolution_px=1)
    width_px, height_px = slot_px_size(slot, output_dpi, cfg, bleed=True)
    fitted = fit_photo(
        photo,
        (width_px, height_px),
        fit=slot.fit,
        zoom=slot.zoom,
        offset_mm=slot.offset_mm,
        rotation_deg=slot.rotation_deg,
        dpi=output_dpi,
    )
    alpha = slot_alpha(slot, output_dpi, cfg)
    fitted.putalpha(alpha)
    return fitted, effective_dpi(slot, photo.size, cfg)


def slots_effective_dpi(
    template: LampTemplate,
    config: Config | None = None,
) -> dict[str, float]:
    """Effective DPI for every slot that has a photo."""
    cfg = config or Config()
    result: dict[str, float] = {}
    for slot in template.slots:
        if slot.image_path is None:
            continue
        with Image.open(slot.image_path) as photo:
            result[slot.id] = effective_dpi(slot, photo.size, cfg)
    return result


# ------------------------------------------------------------------ print sheet
def _polygon_px(
    polygon,
    offset_mm: tuple[float, float],
    dpi: float,
) -> list[tuple[float, float]]:
    offset_x, offset_y = offset_mm
    return [
        (mm_to_px(x + offset_x, dpi), mm_to_px(y + offset_y, dpi))
        for x, y in polygon.exterior.coords
    ]


def render_print_sheet(
    template: LampTemplate,
    config: Config | None = None,
    dpi: float | None = None,
) -> Image.Image:
    """Render `print_sheet.png`: the whole lamp 1:1, transparent background (spec 9.4)."""
    cfg = config or Config()
    output_dpi = dpi if dpi is not None else cfg.print_dpi
    width_mm, height_mm = sheet_size_mm(template, cfg)
    width_px = max(1, round(mm_to_px(width_mm, output_dpi)))
    height_px = max(1, round(mm_to_px(height_mm, output_dpi)))
    canvas = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    offset = sheet_offset_mm(template, cfg)

    if cfg.print_order == "print_then_cut":
        draw = ImageDraw.Draw(canvas)
        outline_points = _polygon_px(template.outline.cut_path, offset, output_dpi)
        draw.line([*outline_points, outline_points[0]], fill=(0, 0, 0, 160), width=1)

    for slot in template.slots:
        if slot.image_path is None:
            continue
        min_x, min_y, _, _ = slot_bbox_mm(slot, cfg, bleed=False)
        target_w, target_h = slot_px_size(slot, output_dpi, cfg, bleed=False)
        photo = io_utils.load_image(slot.image_path, min_resolution_px=1)
        fitted = fit_photo(
            photo,
            (target_w, target_h),
            fit=slot.fit,
            zoom=slot.zoom,
            offset_mm=slot.offset_mm,
            rotation_deg=slot.rotation_deg,
            dpi=output_dpi,
        )
        mask = Image.new("L", (target_w, target_h), 0)
        ImageDraw.Draw(mask).polygon(
            [
                (mm_to_px(x - min_x, output_dpi), mm_to_px(y - min_y, output_dpi))
                for x, y in slot.polygon_mm.exterior.coords
            ],
            fill=255,
        )
        fitted.putalpha(mask)
        paste_x = round(mm_to_px(min_x + offset[0], output_dpi))
        paste_y = round(mm_to_px(min_y + offset[1], output_dpi))
        canvas.paste(fitted, (paste_x, paste_y), fitted)

    draw = ImageDraw.Draw(canvas)
    for element in decor_module.print_elements(template.decor):
        color = (*ImageColor.getrgb(element.color_override or cfg.decor_ink_color), 255)
        draw.polygon(_polygon_px(element.polygon_mm, offset, output_dpi), fill=color)

    if cfg.registration_marks:
        _draw_registration_marks(draw, width_mm, height_mm, output_dpi, cfg)
    return canvas


def _draw_registration_marks(
    draw: ImageDraw.ImageDraw,
    width_mm: float,
    height_mm: float,
    dpi: float,
    config: Config,
) -> None:
    size_px = mm_to_px(config.registration_mark_size_mm, dpi) / 2.0
    circle_px = mm_to_px(config.registration_mark_circle_radius_mm, dpi)
    for center_x_mm, center_y_mm in registration_mark_positions(width_mm, height_mm, config):
        center_x = mm_to_px(center_x_mm, dpi)
        center_y = mm_to_px(center_y_mm, dpi)
        color = (*ImageColor.getrgb(config.decor_ink_color), 255)
        draw.line(
            [(center_x - size_px, center_y), (center_x + size_px, center_y)],
            fill=color,
            width=1,
        )
        draw.line(
            [(center_x, center_y - size_px), (center_x, center_y + size_px)],
            fill=color,
            width=1,
        )
        draw.ellipse(
            [
                (center_x - circle_px, center_y - circle_px),
                (center_x + circle_px, center_y + circle_px),
            ],
            outline=color,
            width=1,
        )


def render_decor_png(
    element: DecorElement,
    dpi: float,
    config: Config | None = None,
) -> Image.Image:
    """Render one printable decor element as an RGBA PNG (specification, 9.3)."""
    cfg = config or Config()
    min_x, min_y, max_x, max_y = element.polygon_mm.bounds
    width_px = max(1, round(mm_to_px(max_x - min_x, dpi)))
    height_px = max(1, round(mm_to_px(max_y - min_y, dpi)))
    image = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    color = (*ImageColor.getrgb(element.color_override or cfg.decor_ink_color), 255)
    points = [
        (mm_to_px(x - min_x, dpi), mm_to_px(y - min_y, dpi))
        for x, y in element.polygon_mm.exterior.coords
    ]
    ImageDraw.Draw(image).polygon(points, fill=color)
    return image


# --------------------------------------------------------------------- export
@dataclass
class ExportResult:
    """Paths and diagnostics of one export run."""

    svg_path: Path
    print_sheet_path: Path | None = None
    photo_paths: dict[str, Path] = field(default_factory=dict)
    decor_paths: dict[str, Path] = field(default_factory=dict)
    manifest_path: Path | None = None
    effective_dpi: dict[str, float] = field(default_factory=dict)
    sheet_size_mm: tuple[float, float] = (0.0, 0.0)
    offset_mm: tuple[float, float] = (0.0, 0.0)
    warnings: list[str] = field(default_factory=list)


def manifest_dict(
    template: LampTemplate,
    config: Config | None = None,
    effective_dpi: dict[str, float] | None = None,
) -> dict:
    """Machine-readable summary of one export (specification, 9.4)."""
    cfg = config or Config()
    dpi_map = effective_dpi or {}
    width_mm, height_mm = sheet_size_mm(template, cfg)
    offset = sheet_offset_mm(template, cfg)
    return {
        "schema": slots_module.SCHEMA_VERSION,
        "app_version": __version__,
        "generated_at": datetime.now(UTC).isoformat(),
        "input_kind": template.input_kind,
        "material": dict(template.material.__dict__),
        "base": dict(template.base.__dict__),
        "scale": slots_module.scale_to_geojson(template.scale),
        "kerf_mm": template.outline.kerf_mm,
        "print_dpi": cfg.print_dpi,
        "print_order": cfg.print_order,
        "sheet_size_mm": [width_mm, height_mm],
        "origin_offset_mm": list(offset),
        "slots": [
            {
                "id": slot.id,
                "polygon": slots_module.polygon_to_geojson(slot.polygon_mm),
                "source": slot.source,
                "image_path": str(slot.image_path) if slot.image_path is not None else None,
                "fit": slot.fit,
                "zoom": slot.zoom,
                "offset_mm": list(slot.offset_mm),
                "rotation_deg": slot.rotation_deg,
                "bleed_mm": slot_bleed_mm(slot, cfg),
                "effective_dpi": dpi_map.get(slot.id),
            }
            for slot in template.slots
        ],
        "decor": [
            {
                "id": element.id,
                "polygon": slots_module.polygon_to_geojson(element.polygon_mm),
                "source": element.source,
                "mode": element.mode,
                "engrave_style": element.engrave_style,
                "color_override": element.color_override,
            }
            for element in template.decor
        ],
    }


def export_bundle(
    template: LampTemplate,
    out_dir: Path | str,
    config: Config | None = None,
) -> ExportResult:
    """Write `lamp_cut.svg`, `print_sheet.png`, per-slot/decor PNGs and `manifest.json`."""
    cfg = config or Config()
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    svg_path = svg_writer.write_cut_svg(
        template.outline,
        out_path / "lamp_cut.svg",
        cfg,
        engrave=decor_module.engrave_polygons(template.decor),
    )

    dpi_map = slots_effective_dpi(template, cfg)
    for slot_id, dpi_value in dpi_map.items():
        if dpi_value < cfg.slot_photo_min_dpi:
            warnings.append(
                f"slot '{slot_id}': efektivni DPI {dpi_value:.0f} je ispod "
                f"{cfg.slot_photo_min_dpi:.0f} — fotografija je premala za štampu"
            )

    photo_paths: dict[str, Path] = {}
    for index, slot in enumerate(template.slots, start=1):
        if slot.image_path is None:
            continue
        image, _ = render_photo_slot(slot, cfg)
        name = f"photo_{index:02d}_{slot.id}.png"
        photo_paths[slot.id] = io_utils.save_png(image, out_path / name, cfg.print_dpi)

    decor_paths: dict[str, Path] = {}
    for index, element in enumerate(decor_module.print_elements(template.decor), start=1):
        image = render_decor_png(element, cfg.print_dpi, cfg)
        name = f"decor_{index:02d}_{element.id}.png"
        decor_paths[element.id] = io_utils.save_png(image, out_path / name, cfg.print_dpi)

    sheet = render_print_sheet(template, cfg)
    print_sheet_path = io_utils.save_png(sheet, out_path / "print_sheet.png", cfg.print_dpi)

    manifest = manifest_dict(template, cfg, dpi_map)
    manifest_path = out_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    width_mm, height_mm = sheet_size_mm(template, cfg)
    return ExportResult(
        svg_path=svg_path,
        print_sheet_path=print_sheet_path,
        photo_paths=photo_paths,
        decor_paths=decor_paths,
        manifest_path=manifest_path,
        effective_dpi=dpi_map,
        sheet_size_mm=(width_mm, height_mm),
        offset_mm=sheet_offset_mm(template, cfg),
        warnings=warnings,
    )
