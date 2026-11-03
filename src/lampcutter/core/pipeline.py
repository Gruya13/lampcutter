"""Pipeline orchestration and per-stage cache (specification, 7.10 and 4.3).

Stages: image -> mask (SAM 2 prompt, --mask-file or manual polygon) -> cleanup
-> scale -> vectorise -> glow inset/holes/tab/simplify -> kerf -> SVG.

`run_pipeline` accepts an optional `PipelineCache`; every stage result is then
computed at most once per cache key. The cache counters are what the
invalidation tests observe (specification, 13.1).
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from PIL import Image, ImageDraw

from lampcutter.config import Config, InputKind
from lampcutter.core import cache as cache_module
from lampcutter.core import geometry, io_utils, mask_ops, svg_writer, vectorize
from lampcutter.core import scale as scale_module
from lampcutter.core.cache import PipelineCache
from lampcutter.core.segmentation import Segmenter, mask_from_file
from lampcutter.models import (
    BaseProfile,
    CutGeometry,
    MaterialProfile,
    Prompt,
    ScaleInfo,
)

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
    nominal: shapely.Polygon | None = None
    mask_raw: np.ndarray | None = None
    mask_clean: np.ndarray | None = None
    clearance: geometry.SlotClearance | None = None
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


def _cached(
    cache: PipelineCache | None,
    stage: cache_module.Stage,
    parts: tuple[Any, ...],
    factory: Callable[[], Any],
) -> Any:
    if cache is None:
        return factory()
    return cache.get(stage, parts, factory)


def _overlay_png(
    image: Image.Image,
    cut_geometry: CutGeometry,
    mm_per_px: float,
    path: Path,
) -> Path:
    """Draw the cut path in red over the source image (debug output)."""
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    points = [(x / mm_per_px, y / mm_per_px) for x, y in cut_geometry.cut_path.exterior.coords]
    draw.line(points, fill=(255, 0, 0), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(path)
    return path


def _preview_svg(
    image: Image.Image,
    cut_geometry: CutGeometry,
    mm_per_px: float,
    path: Path,
) -> Path:
    from shapely.geometry import Polygon

    points = [(x / mm_per_px, y / mm_per_px) for x, y in cut_geometry.cut_path.exterior.coords]
    return svg_writer.write_preview_svg(image, [Polygon(points)], path)


def _material_key(material: MaterialProfile) -> tuple[Any, ...]:
    return (
        material.id,
        material.thickness_mm,
        material.kerf_mm,
        material.min_feature_mm,
    )


def _base_key(base: BaseProfile | None) -> tuple[Any, ...] | None:
    if base is None:
        return None
    return (
        base.id,
        base.tab_width_mm,
        base.tab_height_mm,
        base.tab_fit_mm,
        base.tab_offset_mm,
        base.corner_radius_mm,
    )


def _finish_from_mask(
    image: Image.Image,
    mask_raw: np.ndarray,
    *,
    cfg: Config,
    material: MaterialProfile,
    base: BaseProfile | None,
    input_kind: InputKind,
    height_mm: float,
    reference: str,
    out_path: Path,
    collected_warnings: list[str],
    progress_fn: ProgressCallback,
    cancel: CancelCallback | None,
    cache: PipelineCache | None,
    debug_dir: Path | None,
) -> PipelineResult:
    """Stages after the raw mask: cleanup -> scale -> vectorise -> geometry -> SVG.

    Shared by `run_pipeline` (after segmentation) and `revectorize_mask` (after a
    manual brush retouch), so both paths produce identical output for equal masks.
    """
    component_count = mask_ops.count_components(mask_raw)
    if component_count > 1:
        message = (
            f"Maska ima {component_count} komponente; koristi se najveća (specifikacija, 8.4)."
        )
        warnings.warn(message, RuntimeWarning, stacklevel=2)
        collected_warnings.append(message)

    _progress(progress_fn, "clean", 0.35)
    _check_cancel(cancel)
    mask_clean = _cached(
        cache,
        "S3",
        (cache_module.mask_digest(mask_raw), cfg.mask_smooth_sigma_px),
        lambda: mask_ops.clean_mask(mask_raw, cfg),
    )
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
    polygon_mm = _cached(
        cache,
        "S4",
        (
            cache_module.mask_digest(mask_clean),
            scale_info.mm_per_px,
            scale_info.bbox_px,
            cfg.vectorize_backend,
            cfg.curve_sample_tol_mm,
            cfg.min_edge_mm,
            cfg.vectorize_upsample_threshold_px,
            cfg.potrace_turdsize,
            cfg.potrace_alphamax,
            cfg.potrace_opttolerance,
        ),
        lambda: vectorize.vectorize_mask(mask_clean, scale_info, cfg),
    )

    _progress(progress_fn, "geometry", 0.8)
    _check_cancel(cancel)
    clearance = geometry.slot_clearance(base, material) if base is not None else None
    if clearance is not None:
        for message in clearance.warnings:
            collected_warnings.append(message)

    def compute_geometry() -> tuple[shapely.Polygon, shapely.Geometry, CutGeometry]:
        nominal = geometry.prepare_nominal(polygon_mm, cfg, input_kind, base=base)
        thin = geometry.check_min_feature(
            nominal,
            material.min_feature_mm,
            warn=False,
            min_area_mm2=cfg.thin_feature_min_area_mm2,
        )
        cut = geometry.compute_cut_geometry(
            nominal, material, cfg.kerf_mode, min_edge_mm=cfg.min_edge_mm
        )
        return nominal, thin, cut

    s5_key = (
        cache_module.polygon_digest(polygon_mm),
        _material_key(material),
        _base_key(base),
        input_kind,
        cfg.kerf_mode,
        cfg.edge_inset(input_kind),
        cfg.simplify_tol_mm,
        cfg.min_edge_mm,
        cfg.thin_feature_min_area_mm2,
    )
    nominal, thin, cut_geometry = _cached(cache, "S5", s5_key, compute_geometry)
    if not thin.is_empty and thin.area > cfg.thin_feature_min_area_mm2:
        message = (
            f"Kontura ima delove tanje od {material.min_feature_mm} mm "
            f"({thin.area:.2f} mm²) — proveri pre sečenja."
        )
        collected_warnings.append(message)
        warnings.warn(message, geometry.ThinFeatureWarning, stacklevel=2)

    _progress(progress_fn, "export", 0.9)
    _check_cancel(cancel)
    svg_key = (
        cache_module.cut_geometry_digest(cut_geometry),
        str(out_path),
        cfg.svg_margin_mm,
        cfg.cut_stroke,
        cfg.cut_stroke_width_mm,
    )
    svg_path = _cached(
        cache,
        "S6",
        svg_key,
        lambda: svg_writer.write_cut_svg(cut_geometry, out_path / "lamp_cut.svg", cfg),
    )

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
        nominal=nominal,
        mask_raw=mask_raw,
        mask_clean=mask_clean,
        clearance=clearance,
        debug_paths=debug_paths,
        warnings=collected_warnings,
    )


def run_pipeline(
    image_path: Path | str,
    *,
    prompt: Prompt | None = None,
    mask_file: Path | str | None = None,
    polygon_px: list[tuple[int, int]] | None = None,
    config: Config | None = None,
    material: MaterialProfile,
    base: BaseProfile | None = None,
    input_kind: InputKind = "mockup",
    height_mm: float,
    reference: str = "height",
    out_dir: Path | str = "izlaz",
    debug_dir: Path | str | None = None,
    models_dir: Path | str = "models",
    segmenter: Segmenter | None = None,
    cache: PipelineCache | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> PipelineResult:
    """Run the full cut pipeline for one image (specification, 7.10).

    Exactly one mask source is required: `prompt` (SAM 2), `mask_file` or
    `polygon_px` (manual polygon tool). `segmenter` lets the GUI reuse one loaded
    model; `cache` enables the per-stage cache from specification 4.3.
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
    image_digest = io_utils.file_sha256(image_path)

    sources = sum(source is not None for source in (prompt, mask_file, polygon_px))
    if sources == 0:
        raise PipelineError("Potreban je prompt, --mask-file ili ručni poligon.")
    if sources > 1:
        raise PipelineError("Daj samo jedan izvor maske: prompt, --mask-file ili poligon.")

    _progress(progress_fn, "segment", 0.15)
    _check_cancel(cancel)

    segmenter_obj = segmenter
    multimask = False
    if prompt is not None:
        if segmenter_obj is None:
            segmenter_obj = Segmenter(
                variant=cfg.sam_variant,
                device=cfg.device,
                models_dir=models_dir,
            )
        array = io_utils.image_to_array(working_image)
        _cached(
            cache,
            "S1",
            (image_digest, cfg.sam_variant, cfg.device, id(segmenter_obj)),
            lambda: segmenter_obj.set_image(array),
        )
        multimask = Segmenter.predict_multimask_rule(prompt)

    if mask_file is not None:
        mask_source_key: tuple[Any, ...] = (
            "mask_file",
            io_utils.file_sha256(mask_file),
            working_size,
        )
    elif polygon_px is not None:
        mask_source_key = ("polygon", tuple(tuple(point) for point in polygon_px), working_size)
    else:
        assert prompt is not None
        mask_source_key = (
            "prompt",
            image_digest,
            prompt.points,
            prompt.labels,
            prompt.box,
            working_size,
            multimask,
        )

    refine_key = (input_kind, cfg.refine_edge_photo, cfg.refine_edge_band_px)
    if cache is not None:
        mask_source_key = (*mask_source_key, *refine_key)

    def compute_mask_raw() -> np.ndarray:
        if mask_file is not None:
            working_mask = mask_from_file(mask_file, target_size=working_size)
        elif polygon_px is not None:
            working_mask = mask_ops.polygon_to_mask(polygon_px, working_size[::-1])
        else:
            assert prompt is not None and segmenter_obj is not None
            result = segmenter_obj.predict(prompt, multimask=multimask)
            working_mask = result.mask
        raw = io_utils.mask_to_original(working_mask, factor, original_size)
        if input_kind == "photo" and cfg.refine_edge_photo and raw.any():
            raw = mask_ops.refine_edge(
                io_utils.image_to_array(image),
                raw,
                cfg.refine_edge_band_px,
            )
        return raw

    mask_raw = _cached(cache, "S2", mask_source_key, compute_mask_raw)

    return _finish_from_mask(
        image,
        mask_raw,
        cfg=cfg,
        material=material,
        base=base,
        input_kind=input_kind,
        height_mm=height_mm,
        reference=reference,
        out_path=out_path,
        collected_warnings=collected_warnings,
        progress_fn=progress_fn,
        cancel=cancel,
        cache=cache,
        debug_dir=Path(debug_dir) if debug_dir is not None else None,
    )


def revectorize_mask(
    image_path: Path | str,
    mask: np.ndarray,
    *,
    config: Config | None = None,
    material: MaterialProfile,
    base: BaseProfile | None = None,
    input_kind: InputKind = "mockup",
    height_mm: float,
    reference: str = "height",
    out_dir: Path | str = "izlaz",
    debug_dir: Path | str | None = None,
    cache: PipelineCache | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> PipelineResult:
    """Re-run cleanup/vectorise/geometry/export from an edited mask (v1.1 brush).

    Used by the GUI brush retouch: the mask comes from a previous pipeline run
    and may have been painted/erased by the user. The image is still required for
    the debug overlay and for the mask size.
    """
    cfg = config or Config()
    progress_fn = progress or _noop_progress
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    image = io_utils.load_image(image_path, min_resolution_px=cfg.min_resolution_px)
    binary = np.asarray(mask, dtype=bool)
    if binary.ndim != 2:
        raise PipelineError("Maska mora biti 2-D.")
    if binary.shape != (image.height, image.width):
        resized = Image.fromarray(binary.astype(np.uint8) * 255).resize(
            image.size, Image.Resampling.NEAREST
        )
        binary = np.asarray(resized) > 127
    if not binary.any():
        raise PipelineError("Maska je prazna.")
    return _finish_from_mask(
        image,
        binary,
        cfg=cfg,
        material=material,
        base=base,
        input_kind=input_kind,
        height_mm=height_mm,
        reference=reference,
        out_path=out_path,
        collected_warnings=[],
        progress_fn=progress_fn,
        cancel=cancel,
        cache=cache,
        debug_dir=Path(debug_dir) if debug_dir is not None else None,
    )
