"""Image loading and file helpers (specification, 7.1)."""

from __future__ import annotations

import hashlib
import warnings
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

# Specification, section 3: warn below 1000 px on the longer side.
DEFAULT_MIN_RESOLUTION_PX = 1000


class LowResolutionWarning(UserWarning):
    """The source image is likely too small for a clean 1:1 print."""


def load_image(
    path: Path | str,
    min_resolution_px: int = DEFAULT_MIN_RESOLUTION_PX,
) -> Image.Image:
    """Load an image as RGB, applying EXIF orientation (specification, 3).

    Warns with `LowResolutionWarning` when the longer side is below
    `min_resolution_px`; the image is still returned.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Slika ne postoji: {path}")
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw)
        image = image.convert("RGB")
    longer = max(image.size)
    if longer < min_resolution_px:
        warnings.warn(
            f"Slika je niske rezolucije ({image.width}x{image.height} px, "
            f"preporuka je > {min_resolution_px} px po dužoj strani).",
            LowResolutionWarning,
            stacklevel=2,
        )
    return image


def file_sha256(path: Path | str) -> str:
    """SHA256 of the raw file bytes; the S1 cache key (specification, 4.2)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_png(image: Image.Image, path: Path | str, dpi: int) -> Path:
    """Save a PNG with a DPI metadata tag (specification, 7.1)."""
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", dpi=(dpi, dpi))
    return path


def to_working_size(
    image: Image.Image,
    max_side: int,
) -> tuple[Image.Image, float]:
    """Downscale so the longer side is at most `max_side`.

    Returns `(working_image, factor)` where `factor = working_side / original_side`.
    Images that already fit are returned unchanged with `factor = 1.0`.
    """
    if max_side <= 0:
        raise ValueError("max_side must be positive")
    width, height = image.size
    longer = max(width, height)
    if longer <= max_side:
        return image, 1.0
    factor = max_side / longer
    new_size = (max(1, round(width * factor)), max(1, round(height * factor)))
    resized = image.resize(new_size, Image.Resampling.LANCZOS)
    return resized, new_size[0] / width


def mask_to_original(
    mask: np.ndarray,
    factor: float,
    original_size: tuple[int, int],
) -> np.ndarray:
    """Resize a boolean mask from working size back to the original resolution.

    `original_size` is `(width, height)` as returned by `PIL.Image.size`.
    Nearest-neighbour is used so the mask stays strictly binary.
    """
    if mask.ndim != 2:
        raise ValueError("mask must be a 2-D array")
    width, height = original_size
    if mask.shape == (height, width):
        return mask.astype(bool, copy=True)
    if factor <= 0:
        raise ValueError("factor must be positive")
    resized = Image.fromarray(mask.astype(np.uint8) * 255).resize(
        (width, height), Image.Resampling.NEAREST
    )
    return np.asarray(resized) > 127


def image_to_array(image: Image.Image) -> np.ndarray:
    """PIL RGB image -> H x W x 3 uint8 numpy array."""
    return np.asarray(image.convert("RGB"))


def array_to_image(array: np.ndarray) -> Image.Image:
    """H x W x 3 uint8 numpy array -> PIL image."""
    if array.ndim == 2:
        array = np.repeat(array[:, :, None], 3, axis=2)
    return Image.fromarray(array.astype(np.uint8), mode="RGB")
