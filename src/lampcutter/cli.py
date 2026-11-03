"""Command line interface (specification, section 10)."""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

from lampcutter.config import Config
from lampcutter.core.pipeline import PipelineError, run_pipeline
from lampcutter.models import Prompt
from lampcutter.settings import AppSettings


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
    run_parser.add_argument("--box", type=parse_box, default=None, metavar="X0,Y0,X1,Y1",
                            help="SAM 2 okvir")
    run_parser.add_argument("--mask-file", type=Path, default=None,
                            help="gotova binarna maska (PNG) umesto SAM 2")
    run_parser.add_argument("--height-mm", type=float, required=True,
                            help="stvarna visina izrezanog dela u mm (bez jezička)")
    run_parser.add_argument("--reference", choices=["height", "width"], default="height",
                            help="na koju dimenziju se odnosi --height-mm (podrazumevano height)")
    run_parser.add_argument("--material", default="acrylic-3", help="id profila materijala")
    run_parser.add_argument("--base", default=None,
                            help="id profila baze (jezičak je Faza 0b, ovde se ignoriše)")
    run_parser.add_argument("--input-kind", choices=["mockup", "photo"], default="mockup",
                            help="mockup ili stvarna fotografija")
    run_parser.add_argument("--kerf-mode", choices=["app", "lightburn"], default=None,
                            help="ko radi kerf kompenzaciju (podrazumevano iz config-a)")
    run_parser.add_argument("--device", choices=["auto", "cuda", "mps", "cpu"], default=None,
                            help="uređaj za SAM 2 (podrazumevano auto)")
    run_parser.add_argument(
        "--sam-variant",
        choices=["auto", "tiny", "small", "base_plus", "large"],
        default=None,
        help="SAM 2 varijanta modela",
    )
    run_parser.add_argument("--config", type=Path, default=None, help="opcioni config.toml")
    run_parser.add_argument("--out", type=Path, default=Path("izlaz"), help="izlazni direktorijum")
    run_parser.add_argument("--debug-dir", type=Path, default=None,
                            help="snimi mask_raw/mask_clean/overlay/contour_preview")

    calibrate_parser = subparsers.add_parser("calibrate", help="kalibracioni SVG (Faza 0b)")
    calibrate_parser.add_argument("--sizes", default="20,30,40")
    calibrate_parser.add_argument("--out", type=Path, default=Path("kalibracija"))

    benchmark_parser = subparsers.add_parser("benchmark", help="SAM 2 benchmark (Faza 0b)")
    benchmark_parser.add_argument("--images", type=Path, default=Path("tests/data"))
    benchmark_parser.add_argument("--out", type=Path, default=Path("benchmark_report"))
    return parser


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

    settings = AppSettings.load()
    material = settings.material(args.material)
    prompt = build_prompt(args.point, args.box)
    if args.base is not None:
        settings.base(args.base)  # validate the id early
        print(
            "Napomena: jezičak i baza su deo Faze 0b — --base se za sada ignoriše.",
            file=sys.stderr,
        )
    if prompt is None and args.mask_file is None:
        raise PipelineError("Daj --point/--box (SAM 2) ili --mask-file.")

    result = run_pipeline(
        args.image,
        prompt=prompt,
        mask_file=args.mask_file,
        config=config,
        material=material,
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
    for message in result.warnings:
        print(f"Upozorenje: {message}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `lampcutter` console script."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _run_command(args)
        if args.command in ("calibrate", "benchmark"):
            raise PipelineError(f"Komanda {args.command!r} dolazi u Fazi 0b.")
        raise PipelineError(f"Nepoznata komanda {args.command!r}")
    except (PipelineError, FileNotFoundError, KeyError, ValueError) as error:
        print(f"Greška: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("default")
        raise SystemExit(main())
