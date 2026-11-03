#!/usr/bin/env python3
"""Generate the verification demo template (`tests/data/demo.lamptpl`).

The template is deliberately simple so that physical checks are repeatable:
180 x 230 mm body with a base tab, one photo slot with a synthetic client
photo, two engrave elements (including a 1.5 mm line) and one print element.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw
from shapely.geometry import box

from lampcutter.core import geometry, slots
from lampcutter.models import (
    BaseProfile,
    DecorElement,
    LampTemplate,
    MaterialProfile,
    PhotoSlot,
    ScaleInfo,
)

OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "data"


def make_client_photo(path: Path) -> Path:
    """Synthetic client photo with corner markers (so rotation/zoom is visible)."""
    image = Image.new("RGB", (1200, 900), (25, 30, 45))
    draw = ImageDraw.Draw(image)
    for index in range(6):
        x = 100 + index * 190
        draw.rectangle([x, 120, x + 150, 780], fill=(40 + index * 30, 90, 150 - index * 15))
    # corner markers in different colours
    draw.rectangle([0, 0, 120, 120], fill=(230, 40, 40))
    draw.rectangle([image.width - 120, 0, image.width, 120], fill=(40, 200, 80))
    draw.rectangle([0, image.height - 120, 120, image.height], fill=(240, 210, 40))
    draw.rectangle(
        [image.width - 120, image.height - 120, image.width, image.height],
        fill=(220, 80, 220),
    )
    image.save(path)
    return path


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client_photo = make_client_photo(OUT_DIR / "demo_klijent.png")

    material = MaterialProfile("acrylic-3", "Akril providni 3 mm", 3.0, 0.18)
    # PROVISIONAL placeholder base: Dalibor replaces these with measured values.
    base = BaseProfile(
        id="demo-baza",
        name="Demo baza (zameni izmerenim merama)",
        slot_length_mm=80.0,
        slot_thickness_mm=3.4,
        slot_dimensions="measured",
        tab_width_mm=78.0,
        tab_height_mm=8.0,
    )
    nominal = geometry.add_tab(box(0.0, 0.0, 180.0, 230.0), base)
    cut_geometry = geometry.compute_cut_geometry(nominal, material, "app")

    photo_slot = PhotoSlot(
        id="foto-1",
        polygon_mm=box(30.0, 40.0, 150.0, 130.0),
        source="detected",
        image_path=client_photo,
        fit="cover",
    )
    engrave_frame = DecorElement(
        id="gravura-okvir",
        polygon_mm=box(30.0, 145.0, 150.0, 150.0),
        source="threshold",
        mode="engrave",
        engrave_style="fill",
    )
    engrave_line = DecorElement(
        id="gravura-linija-2mm",
        polygon_mm=box(30.0, 160.0, 150.0, 162.0),
        source="threshold",
        mode="engrave",
        engrave_style="line",
    )
    print_text = DecorElement(
        id="stampa-tekst",
        polygon_mm=box(30.0, 175.0, 150.0, 190.0),
        source="text",
        mode="print",
        color_override="#101010",
    )
    template = LampTemplate(
        outline=cut_geometry,
        slots=[photo_slot],
        decor=[engrave_frame, engrave_line, print_text],
        base=base,
        material=material,
        scale=ScaleInfo(
            mm_per_px=0.1, reference="height", reference_mm=230.0, bbox_px=(0, 0, 1800, 2300)
        ),
        input_kind="mockup",
    )
    path = slots.save_template(template, OUT_DIR / "demo.lamptpl")
    print(f"Demo šablon: {path}")
    print(f"Klijentska fotografija: {client_photo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
