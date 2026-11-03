"""Command line interface (specification, section 10)."""

from __future__ import annotations

import argparse
import dataclasses
import subprocess
import sys
import warnings
from pathlib import Path

from lampcutter.config import Config
from lampcutter.core import calibrate, compose, decor, slots
from lampcutter.core.pipeline import PipelineError, run_pipeline
from lampcutter.models import MaterialProfile, Prompt
from lampcutter.settings import (
    AppSettings,
    load_bases,
    load_materials,
    save_materials,
)


def parse_point(value: str) -> tuple[int, int, int]:
    """Parse `X,Y` or `X,Y:neg` into `(x, y, label)` with label 1=positive, 0=negative."""
    text, _, suffix = value.partition(":")
    label = 1
    if suffix:
        if suffix.lower() in ("neg", "negative", "0"):
            label = 0
        elif suffix.lower() not in ("pos", "positive", "1"):
            raise argparse.ArgumentTypeError(f"neispravna oznaka tačke {suffix!r}")
    parts = text.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"neispravna tačka {value!r}; očekivano X,Y[:neg]")
    try:
        return int(parts[0]), int(parts[1]), label
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"neispravna tačka {value!r}; X i Y su celi brojevi"
        ) from exc


def parse_box(value: str) -> tuple[int, int, int, int]:
    """Parse `X0,Y0,X1,Y1` into a Prompt box."""
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"neispravan okvir {value!r}; očekivano X0,Y0,X1,Y1")
    try:
        x0, y0, x1, y1 = (int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"neispravan okvir {value!r}; vrednosti su celi brojevi"
        ) from exc
    if x1 <= x0 or y1 <= y0:
        raise argparse.ArgumentTypeError("okvir mora da ima x1 > x0 i y1 > y0")
    return x0, y0, x1, y1


def build_prompt(
    points: list[tuple[int, int, int]] | None,
    box: tuple[int, int, int, int] | None,
) -> Prompt | None:
    """Turn parsed CLI arguments into a Prompt (or None when there is no prompt)."""
    points = points or []
    if not points and box is None:
        return None
    return Prompt(
        points=tuple((x, y) for x, y, _ in points),
        labels=tuple(label for _, _, label in points),
        box=box,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lampcutter",
        description="Pretvara sliku dizajna akrilne lampe u SVG za sečenje u milimetrima.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="obradi jednu sliku i izvezi SVG")
    run_parser.add_argument("image", type=Path, help="slika dizajna (JPG/PNG/WEBP)")
    run_parser.add_argument(
        "--point",
        action="append",
        type=parse_point,
        default=[],
        metavar="X,Y[:neg]",
        help="SAM 2 tačka; :neg označava negativnu tačku (ponavlja se)",
    )
    run_parser.add_argument(
        "--box", type=parse_box, default=None, metavar="X0,Y0,X1,Y1", help="SAM 2 okvir"
    )
    run_parser.add_argument(
        "--mask-file", type=Path, default=None, help="gotova binarna maska (PNG) umesto SAM 2"
    )
    run_parser.add_argument(
        "--height-mm",
        type=float,
        required=True,
        help="stvarna visina izrezanog dela u mm (bez jezička)",
    )
    run_parser.add_argument(
        "--reference",
        choices=["height", "width"],
        default="height",
        help="na koju dimenziju se odnosi --height-mm (podrazumevano height)",
    )
    run_parser.add_argument("--material", default="acrylic-3", help="id profila materijala")
    run_parser.add_argument(
        "--base", default=None, help="id profila baze; dodaje jezičak i računa zazor"
    )
    run_parser.add_argument(
        "--input-kind",
        choices=["mockup", "photo"],
        default="mockup",
        help="mockup ili stvarna fotografija",
    )
    run_parser.add_argument(
        "--kerf-mode",
        choices=["app", "lightburn"],
        default=None,
        help="ko radi kerf kompenzaciju (podrazumevano iz config-a)",
    )
    run_parser.add_argument(
        "--device",
        choices=["auto", "cuda", "mps", "cpu"],
        default=None,
        help="uređaj za SAM 2 (podrazumevano auto)",
    )
    run_parser.add_argument(
        "--sam-variant",
        choices=["auto", "tiny", "small", "base_plus", "large"],
        default=None,
        help="SAM 2 varijanta modela",
    )
    run_parser.add_argument("--config", type=Path, default=None, help="opcioni config.toml")
    run_parser.add_argument("--out", type=Path, default=Path("izlaz"), help="izlazni direktorijum")
    run_parser.add_argument(
        "--debug-dir",
        type=Path,
        default=None,
        help="snimi mask_raw/mask_clean/overlay/contour_preview",
    )

    calibrate_parser = subparsers.add_parser(
        "calibrate", help="kalibracioni SVG za merenje kerfa (specifikacija, 7.9)"
    )
    calibrate_parser.add_argument("--sizes", default="20,30,40", help="nominalne veličine u mm")
    calibrate_parser.add_argument(
        "--measured",
        default=None,
        help="izmerene veličine posle rezanja (isti redosled), za računanje kerfa",
    )
    calibrate_parser.add_argument(
        "--material", default=None, help="id profila u koji se upisuje izmereni kerf"
    )
    calibrate_parser.add_argument(
        "--spacing", type=float, default=calibrate.DEFAULT_SPACING_MM, help="razmak između kvadrata"
    )
    calibrate_parser.add_argument("--config", type=Path, default=None, help="opcioni config.toml")
    calibrate_parser.add_argument(
        "--materials-file",
        type=Path,
        default=None,
        help="JSON u koji se upisuje izmereni kerf (umesto korisničkog foldera)",
    )
    calibrate_parser.add_argument(
        "--out", type=Path, default=Path("kalibracija"), help="izlazni direktorijum"
    )

    export_parser = subparsers.add_parser(
        "export",
        help="izvezi lamp_cut.svg, print_sheet.png, photo/decor PNG i manifest.json iz .lamptpl",
    )
    export_parser.add_argument("--template", type=Path, required=True, help=".lamptpl fajl")
    export_parser.add_argument(
        "--out", type=Path, default=Path("izlaz"), help="izlazni direktorijum"
    )
    export_parser.add_argument("--config", type=Path, default=None, help="opcioni config.toml")
    export_parser.add_argument("--print-dpi", type=int, default=None, help="DPI za štampu")
    export_parser.add_argument(
        "--print-order",
        choices=["cut_then_print", "print_then_cut"],
        default=None,
        help="redosled sečenja i štampe",
    )

    gui_parser = subparsers.add_parser("gui", help="pokreni grafički interfejs (zahteva PySide6)")
    gui_parser.add_argument(
        "image", type=Path, nargs="?", default=None, help="slika koja se odmah učitava"
    )
    gui_parser.add_argument("--theme", choices=["dark", "light"], default="dark", help="tema")
    gui_parser.add_argument(
        "--device", choices=["auto", "cuda", "mps", "cpu"], default=None, help="uređaj za SAM 2"
    )
    gui_parser.add_argument(
        "--sam-variant",
        choices=["auto", "tiny", "small", "base_plus", "large"],
        default=None,
        help="SAM 2 varijanta modela",
    )

    benchmark_parser = subparsers.add_parser(
        "benchmark", help="SAM 2 benchmark (specifikacija, 11.2); prosleđuje argumente skripti"
    )
    benchmark_parser.add_argument(
        "benchmark_args",
        nargs=argparse.REMAINDER,
        help="argumenti za scripts/benchmark.py (npr. --images tests/data --out benchmark_report)",
    )
    return parser


def _load_settings(args: argparse.Namespace) -> AppSettings:
    """User settings, optionally overridden by explicit profile JSON files."""
    settings = AppSettings.load()
    materials_file = getattr(args, "materials_file", None)
    bases_file = getattr(args, "bases_file", None)
    if materials_file is not None:
        settings.materials = load_materials(materials_file)
    if bases_file is not None:
        settings.bases = load_bases(bases_file)
    return settings


def _progress_printer(stage: str, fraction: float) -> None:
    print(f"  [{fraction * 100:5.1f}%] {stage}", file=sys.stderr)


def _run_command(args: argparse.Namespace) -> int:
    config = Config.from_toml(args.config) if args.config is not None else Config()
    if args.kerf_mode is not None:
        config.kerf_mode = args.kerf_mode
    if args.device is not None:
        config.device = args.device
    if args.sam_variant is not None:
        config.sam_variant = args.sam_variant

    settings = _load_settings(args)
    material = settings.material(args.material)
    base = settings.base(args.base) if args.base is not None else None
    prompt = build_prompt(args.point, args.box)
    if prompt is None and args.mask_file is None:
        raise PipelineError("Daj --point/--box (SAM 2) ili --mask-file.")

    result = run_pipeline(
        args.image,
        prompt=prompt,
        mask_file=args.mask_file,
        config=config,
        material=material,
        base=base,
        input_kind=args.input_kind,
        height_mm=args.height_mm,
        reference=args.reference,
        out_dir=args.out,
        debug_dir=args.debug_dir,
        progress=_progress_printer,
    )
    print(f"SVG: {result.svg_path}")
    print(
        f"Dimenzije: {result.scale.width_mm:.2f} x {result.scale.height_mm:.2f} mm "
        f"(mm/px = {result.scale.mm_per_px:.5f}), kerf = {result.cut_geometry.kerf_mm} mm"
    )
    if result.clearance is not None:
        clearance = result.clearance
        print(
            f"Prorez: efektivna dužina {clearance.effective_slot_length_mm:.2f} mm, "
            f"zazor u ravni {clearance.planar_clearance_mm:+.2f} mm, "
            f"po debljini {clearance.thickness_clearance_mm:+.2f} mm"
        )
    for message in result.warnings:
        print(f"Upozorenje: {message}", file=sys.stderr)
    return 0


def _calibrate_command(args: argparse.Namespace) -> int:
    config = Config.from_toml(args.config) if args.config is not None else Config()
    sizes = calibrate.parse_sizes(args.sizes)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    svg_path = calibrate.build_calibration_svg(
        sizes, out_dir / "kalibracija.svg", config, spacing_mm=args.spacing
    )
    print(f"Kalibracioni SVG: {svg_path}")
    print("Odseci kvadrate, izmeri svaki pomičnim merilom i unesi --measured ...")

    if args.measured is None:
        return 0
    measured = calibrate.parse_sizes(args.measured)
    measurements = calibrate.measurements_from_lists(sizes, measured)
    for item in measurements:
        print(
            f"  {item.nominal_mm:.2f} mm - {item.measured_mm:.2f} mm = kerf {item.kerf_mm:+.3f} mm"
        )
    kerf = calibrate.average_kerf(measurements)
    print(f"Prosečan kerf: {kerf:.3f} mm")

    if args.material is not None:
        settings = _load_settings(args)
        material = settings.material(args.material)
        updated = MaterialProfile(
            id=material.id,
            name=material.name,
            thickness_mm=material.thickness_mm,
            kerf_mm=kerf,
            min_feature_mm=material.min_feature_mm,
            notes=material.notes,
        )
        materials = [updated if item.id == material.id else item for item in settings.materials]
        path = save_materials(materials, args.materials_file)
        print(f"Kerf upisan u profil {material.id}: {path}")
    return 0


def _benchmark_command(args: argparse.Namespace) -> int:
    script = Path(__file__).resolve().parents[2] / "scripts" / "benchmark.py"
    if not script.exists():
        raise PipelineError("scripts/benchmark.py nije pronađen (pokreni iz izvornog repoa).")
    completed = subprocess.run(
        [sys.executable, str(script), *args.benchmark_args],
        check=False,
    )
    return completed.returncode


def _export_command(args: argparse.Namespace) -> int:
    config = Config.from_toml(args.config) if args.config is not None else Config()
    if args.print_dpi is not None:
        config = dataclasses.replace(config, print_dpi=args.print_dpi)
    if args.print_order is not None:
        config = dataclasses.replace(config, print_order=args.print_order)

    template = slots.load_template(args.template)
    decor_warnings = decor.decor_warnings(
        template.decor,
        template.outline.nominal,
        template.material,
        config.engrave_margin_mm,
        config,
    )
    result = compose.export_bundle(template, args.out, config)
    print(f"SVG: {result.svg_path}")
    if result.print_sheet_path is not None:
        print(f"Print sheet: {result.print_sheet_path}")
    if result.photo_paths:
        print("Photo: " + ", ".join(str(path) for path in result.photo_paths.values()))
    if result.decor_paths:
        print("Dekor: " + ", ".join(str(path) for path in result.decor_paths.values()))
    if result.manifest_path is not None:
        print(f"Manifest: {result.manifest_path}")
    if result.effective_dpi:
        dpi_text = ", ".join(
            f"{slot_id}={dpi:.0f}" for slot_id, dpi in result.effective_dpi.items()
        )
        print(f"Efektivni DPI: {dpi_text}")
    for message in decor_warnings + result.warnings:
        print(f"Upozorenje: {message}", file=sys.stderr)
    return 0


def _gui_command(args: argparse.Namespace) -> int:
    try:
        from lampcutter.ui.app import run_gui
    except ImportError as error:
        raise PipelineError(
            "GUI zahteva PySide6: uv pip install PySide6==6.12.0 "
            f"(ili uv sync --extra gui). Detalj: {error}"
        ) from error
    return run_gui(
        dark=args.theme == "dark",
        initial_image=str(args.image) if args.image is not None else None,
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `lampcutter` console script."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _run_command(args)
        if args.command == "calibrate":
            return _calibrate_command(args)
        if args.command == "export":
            return _export_command(args)
        if args.command == "gui":
            return _gui_command(args)
        if args.command == "benchmark":
            return _benchmark_command(args)
        raise PipelineError(f"Nepoznata komanda {args.command!r}")
    except (PipelineError, FileNotFoundError, KeyError, ValueError) as error:
        print(f"Greška: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("default")
        raise SystemExit(main())
