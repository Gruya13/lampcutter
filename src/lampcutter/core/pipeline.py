"""Pipeline orchestration (specification, 7.10).

Phase 0a pipeline: image -> mask (SAM 2 prompt, --mask-file or a manual polygon)
-> mask cleanup -> scale -> vectorisation -> glow inset/holes/simplify -> kerf
-> SVG, with optional debug artefacts.

PipelineCache (per-stage hashing) belongs to phase 0b; this module is written so
that the stages can be wrapped by such a cache without changing them.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from lampcutter.config import Config, InputKind
from lampcutter.core import geometry, io_utils, mask_ops, svg_writer, vectorize
from lampcutter.core import scale as scale_module
from lampcutter.core.segmentation import Segmenter, mask_from_file
from lampcutter.models import CutGeometry, MaterialProfile, Prompt, ScaleInfo

ProgressCallback = Callable[[str, float], None]
CancelCallback = Callable[[], bool]


class PipelineError(RuntimeError):
    """The pipeline cannot produce a cut file from the given inputs."""


@dataclass
class PipelineResult:
    """Everything one pipeline run produced, ready for the CLI/GUI."""

    cut_geometry: CutGeometry
    scale: ScaleInfo
    svg_path: Path
    mask_raw: np.ndarray | None = None
    mask_clean: np.ndarray | None = None
    debug_paths: dict[str, Path] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _noop_progress(stage: str, fraction: float) -> None:
    return None


def _check_cancel(cancel: CancelCallback | None) -> None:
    if cancel is not None and cancel():
        raise PipelineError("Obrada je otkazana.")


def _progress(progress: ProgressCallback | None, stage: str, fraction: float) -> None:
    if progress is not None:
        progress(stage, fraction)


def _mask_from_prompt(
    image: Image.Image,
    prompt: Prompt,
    config: Config,
    models_dir: Path | str,
) -> np.ndarray:
    """Run SAM 2 on the working-size image and return a mask at the same size."""
    segmenter = Segmenter(
        variant=config.sam_variant,
        device=config.device,
        models_dir=models_dir,
    )
    segmenter.set_image(io_utils.image_to_array(image))
    multimask = Segmenter.predict_multimask_rule(prompt)
    return segmenter.predict(prompt, multimask=multimask).mask


def _overlay_png(
    image: Image.Image,
    geometry_mm: CutGeometry,
    mm_per_px: float,
    path: Path,
) -> Path:
    """Draw the cut path in red over the source image (debug output)."""
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    points = [(x / mm_per_px, y / mm_per_px) for x, y in geometry_mm.cut_path.exterior.coords]
    draw.line(points, fill=(255, 0, 0), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(path)
    return path


def _preview_svg(
    image: Image.Image,
    geometry_mm: CutGeometry,
    mm_per_px: float,
    path: Path,
) -> Path:
    from shapely.geometry import Polygon

    points = [(x / mm_per_px, y / mm_per_px) for x, y in geometry_mm.cut_path.exterior.coords]
    return svg_writer.write_preview_svg(image, [Polygon(points)], path)


def run_pipeline(
    image_path: Path | str,
    *,
    prompt: Prompt | None = None,
    mask_file: Path | str | None = None,
    polygon_px: list[tuple[int, int]] | None = None,
    config: Config | None = None,
    material: MaterialProfile,
    input_kind: InputKind = "mockup",
    height_mm: float,
    reference: str = "height",
    out_dir: Path | str = "izlaz",
    debug_dir: Path | str | None = None,
    models_dir: Path | str = "models",
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> PipelineResult:
    """Run the full cut pipeline for one image (specification, 7.10).

    Exactly one mask source is required: `prompt` (SAM 2), `mask_file` or
    `polygon_px` (manual polygon tool). `base`/the tab are phase 0b.
    """
    cfg = config or Config()
    progress_fn = progress or _noop_progress
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    collected_warnings: list[str] = []

    _progress(progress_fn, "load", 0.0)
    _check_cancel(cancel)
    image = io_utils.load_image(image_path, min_resolution_px=cfg.min_resolution_px)
    original_size = image.size
    working_image, factor = io_utils.to_working_size(image, cfg.max_side_px)
    working_size = working_image.size
    working_mask = np.zeros((working_size[1], working_size[0]), dtype=bool)

    sources = sum(source is not None for source in (prompt, mask_file, polygon_px))
    if sources == 0:
        raise PipelineError("Potreban je prompt, --mask-file ili ručni poligon.")
    if sources > 1:
        raise PipelineError("Daj samo jedan izvor maske: prompt, --mask-file ili poligon.")

    _progress(progress_fn, "segment", 0.15)
    _check_cancel(cancel)
    if mask_file is not None:
        loaded = mask_from_file(mask_file, target_size=working_size)
        working_mask = loaded
    elif polygon_px is not None:
        working_mask = mask_ops.polygon_to_mask(polygon_px, working_size[::-1])
    else:
        assert prompt is not None
        working_mask = _mask_from_prompt(working_image, prompt, cfg, models_dir)

    mask_raw = io_utils.mask_to_original(working_mask, factor, original_size)
    component_count = mask_ops.count_components(mask_raw)
    if component_count > 1:
        message = (
            f"Maska ima {component_count} komponente; koristi se najveća (specifikacija, 8.4)."
        )
        warnings.warn(message, RuntimeWarning, stacklevel=2)
        collected_warnings.append(message)

    _progress(progress_fn, "clean", 0.35)
    _check_cancel(cancel)
    mask_clean = mask_ops.clean_mask(mask_raw, cfg)
    if not mask_clean.any():
        raise PipelineError("Maska je prazna nakon čišćenja.")

    _progress(progress_fn, "scale", 0.5)
    _check_cancel(cancel)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        scale_info = scale_module.compute_scale(mask_clean, reference, height_mm)
        for warning_item in caught:
            collected_warnings.append(str(warning_item.message))

    _progress(progress_fn, "vectorize", 0.65)
    _check_cancel(cancel)
    polygon_mm = vectorize.vectorize_mask(mask_clean, scale_info, cfg)

    _progress(progress_fn, "geometry", 0.8)
    _check_cancel(cancel)
    nominal = geometry.prepare_nominal(polygon_mm, cfg, input_kind)
    thin = geometry.check_min_feature(
        nominal,
        material.min_feature_mm,
        warn=False,
        min_area_mm2=cfg.thin_feature_min_area_mm2,
    )
    if not thin.is_empty and thin.area > cfg.thin_feature_min_area_mm2:
        message = (
            f"Kontura ima delove tanje od {material.min_feature_mm} mm "
            f"({thin.area:.2f} mm²) — proveri pre sečenja."
        )
        collected_warnings.append(message)
        warnings.warn(message, geometry.ThinFeatureWarning, stacklevel=2)
    cut_geometry = geometry.compute_cut_geometry(
        nominal, material, cfg.kerf_mode, min_edge_mm=cfg.min_edge_mm
    )

    _progress(progress_fn, "export", 0.9)
    _check_cancel(cancel)
    svg_path = svg_writer.write_cut_svg(cut_geometry, out_path / "lamp_cut.svg", cfg)

    debug_paths: dict[str, Path] = {}
    if debug_dir is not None:
        debug_path = Path(debug_dir)
        debug_path.mkdir(parents=True, exist_ok=True)
        debug_paths["mask_raw"] = io_utils.save_png(
            Image.fromarray(mask_raw.astype(np.uint8) * 255),
            debug_path / "mask_raw.png",
            cfg.print_dpi,
        )
        debug_paths["mask_clean"] = io_utils.save_png(
            Image.fromarray(mask_clean.astype(np.uint8) * 255),
            debug_path / "mask_clean.png",
            cfg.print_dpi,
        )
        debug_paths["overlay"] = _overlay_png(
            image, cut_geometry, scale_info.mm_per_px, debug_path / "overlay.png"
        )
        debug_paths["contour_preview"] = _preview_svg(
            image, cut_geometry, scale_info.mm_per_px, debug_path / "contour_preview.svg"
        )

    _progress(progress_fn, "done", 1.0)
    return PipelineResult(
        cut_geometry=cut_geometry,
        scale=scale_info,
        svg_path=svg_path,
        mask_raw=mask_raw,
        mask_clean=mask_clean,
        debug_paths=debug_paths,
        warnings=collected_warnings,
    )
