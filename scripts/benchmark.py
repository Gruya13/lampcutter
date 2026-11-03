#!/usr/bin/env python3
"""SAM 2 benchmark (specification, 11.2).

Measures model load time, set_image time, predict time and peak memory for each
SAM 2 variant on the current machine, and (optionally) the edge deviation in
millimetres against reference masks (specification, 13.2).

The script is written to be run by the user on the target hardware:

* Linux/Windows with an NVIDIA GPU (CUDA),
* macOS Apple Silicon (MPS),
* or this development machine (CPU fallback).

Run it through uv so the locked dependency versions are used:

    uv run python scripts/benchmark.py --images tests/data --out benchmark_report

Reference masks are optional: `tests/data/ref/<stem>.png` is compared against
`tests/data/<stem>.<ext>`.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

from lampcutter.config import Config
from lampcutter.core import device as device_module
from lampcutter.core import io_utils
from lampcutter.core.segmentation import Segmenter, mask_from_file
from lampcutter.models import Prompt

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
DEFAULT_VARIANTS = ("tiny", "small", "base_plus", "large")


def list_images(directory: Path) -> list[Path]:
    """Images directly inside `directory` (the `ref/` subfolder is ignored)."""
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def peak_ram_mb() -> float | None:
    """Peak resident set size of this process in MiB (Linux/macOS)."""
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        # ru_maxrss is KiB on Linux and bytes on macOS.
        divisor = 1024 if sys.platform != "darwin" else 1024 * 1024
        return usage.ru_maxrss / divisor
    except ImportError:
        return None


def peak_vram_mb(device: str) -> float | None:
    """Peak allocated GPU memory in MiB, when the framework exposes it."""
    if not device_module.torch_available():
        return None
    try:
        import torch

        if device == "cuda" and torch.cuda.is_available():
            return torch.cuda.max_memory_allocated() / (1024**2)
        if device == "mps" and device_module.mps_available():
            return torch.mps.current_allocated_memory() / (1024**2)
    except (ImportError, RuntimeError):
        return None
    return None


def reset_peak_memory(device: str) -> None:
    if not device_module.torch_available():
        return
    try:
        import torch

        if device == "cuda" and torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except (ImportError, RuntimeError):
        return


def edge_deviation_mm(
    mask: np.ndarray,
    reference: np.ndarray,
    mm_per_px: float,
) -> dict[str, float] | None:
    """Mean edge deviation and Hausdorff95 in millimetres (specification, 13.2).

    IoU is deliberately not the primary metric: it is blind to edge errors on
    large objects.
    """
    if mask.shape != reference.shape:
        resized = cv2.resize(
            mask.astype(np.uint8),
            (reference.shape[1], reference.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )
        mask = resized.astype(bool)
    kernel = np.ones((3, 3), np.uint8)

    def edges(binary: np.ndarray) -> np.ndarray:
        eroded = cv2.erode(binary.astype(np.uint8), kernel)
        return (binary.astype(np.uint8) - eroded).astype(bool)

    edge_mask = edges(mask)
    edge_ref = edges(reference)
    if not edge_mask.any() or not edge_ref.any():
        return None

    def distances(source: np.ndarray, target: np.ndarray) -> np.ndarray:
        distance = cv2.distanceTransform((~target).astype(np.uint8), cv2.DIST_L2, 5)
        return distance[source]

    forward = distances(edge_mask, edge_ref)
    backward = distances(edge_ref, edge_mask)
    mean_mm = (float(forward.mean()) + float(backward.mean())) / 2.0 * mm_per_px
    hausdorff95_mm = max(
        float(np.percentile(forward, 95)), float(np.percentile(backward, 95))
    ) * mm_per_px
    return {"mean_edge_deviation_mm": mean_mm, "hausdorff95_mm": hausdorff95_mm}


def benchmark_variant(
    variant: str,
    device: str,
    images: list[Path],
    config: Config,
    models_dir: Path,
    reference_mm: dict[str, float] | None,
    repeat: int,
) -> dict:
    """Measure one SAM 2 variant on every image."""
    segmenter = Segmenter(variant=variant, device=device, models_dir=models_dir)
    load_start = time.perf_counter()
    segmenter.load()
    load_seconds = time.perf_counter() - load_start

    image_results = []
    for image_path in images:
        image = io_utils.load_image(image_path, min_resolution_px=1)
        working, factor = io_utils.to_working_size(image, config.max_side_px)
        array = io_utils.image_to_array(working)
        original_size = image.size
        height, width = working.size[1], working.size[0]
        prompt = Prompt(points=((width // 2, height // 2),), labels=(1,))

        reset_peak_memory(device)
        set_image_start = time.perf_counter()
        segmenter.set_image(array)
        set_image_seconds = time.perf_counter() - set_image_start

        predict_seconds = []
        result = None
        for _ in range(repeat):
            predict_start = time.perf_counter()
            result = segmenter.predict(prompt, multimask=True)
            predict_seconds.append(time.perf_counter() - predict_start)

        entry: dict = {
            "image": str(image_path),
            "set_image_s": set_image_seconds,
            "predict_s_mean": statistics.fmean(predict_seconds),
            "predict_s_min": min(predict_seconds),
            "score": result.score if result is not None else None,
            "peak_vram_mb": peak_vram_mb(device),
        }
        if result is not None and reference_mm is not None:
            height_mm = reference_mm.get(image_path.stem)
            reference_path = image_path.parent / "ref" / f"{image_path.stem}.png"
            if height_mm is not None and reference_path.exists():
                mask = io_utils.mask_to_original(result.mask, factor, original_size)
                reference = mask_from_file(reference_path, target_size=original_size)
                known_height_px = int(reference.any(axis=1).sum())
                mm_per_px = height_mm / max(1, known_height_px)
                metrics = edge_deviation_mm(mask, reference, mm_per_px)
                if metrics is not None:
                    entry.update(metrics)
        image_results.append(entry)

    return {
        "variant": variant,
        "device": device,
        "load_s": load_seconds,
        "images": image_results,
        "peak_ram_mb": peak_ram_mb(),
    }


def environment_info() -> dict:
    """What machine the benchmark ran on (needed to compare results)."""
    info: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": __import__("os").cpu_count(),
        "ram_gb": device_module.system_ram_gb(),
        "torch_available": device_module.torch_available(),
    }
    if device_module.torch_available():
        import torch

        info["torch"] = torch.__version__
        info["cuda_available"] = torch.cuda.is_available()
        info["mps_available"] = device_module.mps_available()
        if torch.cuda.is_available():
            info["gpu"] = torch.cuda.get_device_name(0)
            info["vram_gb"] = device_module.cuda_vram_gb()
    return info


def render_markdown(report: dict) -> str:
    """Human-readable summary of the benchmark run."""
    lines = [
        "# SAM 2 benchmark",
        "",
        f"- generisano: {report['environment']['generated_at']}",
        f"- platforma: {report['environment']['platform']}",
        f"- uređaj: {report['device']}",
        f"- torch: {report['environment'].get('torch', 'nije instaliran')}",
        "",
        "| varijanta | učitavanje (s) | set_image (s) | predict (s) | VRAM (MB) | RAM (MB) |",
        "|---|---|---|---|---|---|",
    ]
    for entry in report["variants"]:
        if not entry["images"]:
            lines.append(
                f"| {entry['variant']} | {entry['load_s']:.2f} | — | — | — | "
                f"{entry.get('peak_ram_mb') or 0:.0f} |"
            )
            continue
        set_image = statistics.fmean(item["set_image_s"] for item in entry["images"])
        predict = statistics.fmean(item["predict_s_mean"] for item in entry["images"])
        vram = entry["images"][0].get("peak_vram_mb")
        lines.append(
            f"| {entry['variant']} | {entry['load_s']:.2f} | {set_image:.2f} | "
            f"{predict:.2f} | {vram:.0f} | {entry.get('peak_ram_mb') or 0:.0f} |"
            if vram is not None
            else f"| {entry['variant']} | {entry['load_s']:.2f} | {set_image:.2f} | "
            f"{predict:.2f} | — | {entry.get('peak_ram_mb') or 0:.0f} |"
        )
    edge_rows = [
        (entry["variant"], item["image"], item["mean_edge_deviation_mm"], item["hausdorff95_mm"])
        for entry in report["variants"]
        for item in entry["images"]
        if "mean_edge_deviation_mm" in item
    ]
    if edge_rows:
        lines += [
            "",
            "## Odstupanje ivice (mm, specifikacija 13.2)",
            "",
            "| varijanta | slika | srednje | Hausdorff95 |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {variant} | {Path(image).name} | {mean:.3f} | {hd95:.3f} |"
            for variant, image, mean, hd95 in edge_rows
        ]
    lines.append("")
    return "\n".join(lines)


def parse_variants(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_reference_mm(value: str) -> dict[str, float]:
    """Parse `stem=height_mm` pairs separated by commas."""
    mapping: dict[str, float] = {}
    for pair in value.split(","):
        if not pair.strip():
            continue
        stem, _, height = pair.partition("=")
        mapping[stem.strip()] = float(height)
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SAM 2 benchmark (specifikacija, 11.2)")
    parser.add_argument("--images", type=Path, default=Path("tests/data"))
    parser.add_argument("--out", type=Path, default=Path("benchmark_report"))
    parser.add_argument("--variants", default=",".join(DEFAULT_VARIANTS))
    parser.add_argument("--device", choices=["auto", "cuda", "mps", "cpu"], default="auto")
    parser.add_argument("--models-dir", type=Path, default=Path("models"))
    parser.add_argument("--max-side", type=int, default=2048)
    parser.add_argument("--repeat", type=int, default=3,
                        help="broj predict poziva po slici (podrazumevano 3)")
    parser.add_argument("--reference-mm", default="",
                        help="visine za referentne maske, npr. slika1=250,slika2=180")
    args = parser.parse_args(argv)

    repeat = max(1, args.repeat)
    if not device_module.torch_available():
        print(
            "torch nije instaliran: benchmark traži ML grupu zavisnosti.\n"
            "Instaliraj sa: uv sync --extra ml && uv run python scripts/fetch_models.py",
            file=sys.stderr,
        )
        return 2

    images = list_images(args.images)
    if not images:
        print(
            f"Nema slika u {args.images}. Dodaj test slike (specifikacija, 13.3) "
            "i referentne maske u tests/data/ref/.",
            file=sys.stderr,
        )
        return 2

    device = device_module.pick_device(args.device)
    config = Config(max_side_px=args.max_side)
    references = parse_reference_mm(args.reference_mm) if args.reference_mm else None
    report: dict = {
        "environment": environment_info(),
        "device": device,
        "variants": [],
    }
    for variant in parse_variants(args.variants):
        print(f"[benchmark] varijanta={variant} uređaj={device} ...", file=sys.stderr)
        try:
            report["variants"].append(
                benchmark_variant(
                    variant, device, images, config, args.models_dir, references, repeat
                )
            )
        except device_module.ModelUnavailableError as error:
            print(f"[benchmark] {variant}: {error}", file=sys.stderr)
            report["variants"].append(
                {"variant": variant, "device": device, "error": str(error), "images": []}
            )

    args.out.mkdir(parents=True, exist_ok=True)
    json_path = args.out / "benchmark.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path = args.out / "BENCHMARK.md"
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"JSON: {json_path}")
    print(f"Izveštaj: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
