"""SAM 2 wrapper and mask loading (specification, 7.3).

The ML stack is imported lazily so that the geometric pipeline keeps working on
machines without torch/sam2 (for example the cut path with `--mask-file`).
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
from PIL import Image

from lampcutter.core import device as device_module
from lampcutter.models import Prompt, SegmentationResult

# SAM 2.1 configuration names, to be re-verified against the installed package
# version (specification, 7.3). Checkpoints are expected in `models/`.
VARIANT_CONFIGS: dict[str, str] = {
    "tiny": "configs/sam2.1/sam2.1_hiera_t.yaml",
    "small": "configs/sam2.1/sam2.1_hiera_s.yaml",
    "base_plus": "configs/sam2.1/sam2.1_hiera_b+.yaml",
    "large": "configs/sam2.1/sam2.1_hiera_l.yaml",
}
VARIANT_CHECKPOINTS: dict[str, str] = {
    "tiny": "sam2.1_hiera_tiny.pt",
    "small": "sam2.1_hiera_small.pt",
    "base_plus": "sam2.1_hiera_base_plus.pt",
    "large": "sam2.1_hiera_large.pt",
}
DEFAULT_MODELS_DIR = Path("models")


class SegmentationError(RuntimeError):
    """Segmentation could not produce a mask."""


def mask_from_file(path: Path | str, target_size: tuple[int, int] | None = None) -> np.ndarray:
    """Load a binary PNG mask (specification, 7.3).

    `target_size` is `(width, height)`; when the file differs, it is resized with
    nearest-neighbour so the mask stays strictly binary.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Maska ne postoji: {path}")
    with Image.open(path) as raw:
        mask = np.asarray(raw.convert("L")) > 127
    if target_size is not None:
        width, height = target_size
        if mask.shape != (height, width):
            resized = Image.fromarray(mask.astype(np.uint8) * 255).resize(
                (width, height), Image.Resampling.NEAREST
            )
            mask = np.asarray(resized) > 127
    return mask


class Segmenter:
    """Thin wrapper around `SAM2ImagePredictor` (specification, 7.3).

    The image embedding is computed once per image in `set_image`; every
    `predict` after that is cheap enough for interactive use.
    """

    def __init__(
        self,
        variant: str = "auto",
        device: str = "auto",
        models_dir: Path | str = DEFAULT_MODELS_DIR,
    ) -> None:
        self.requested_variant = variant
        self.requested_device = device
        self.models_dir = Path(models_dir)
        self._predictor = None
        self._resolved_variant: str | None = None
        self._resolved_device: str | None = None
        self._image_set = False

    # -- lazy model loading ---------------------------------------------------
    @property
    def variant(self) -> str:
        if self._resolved_variant is not None:
            return self._resolved_variant
        device = device_module.pick_device(self.requested_device)
        if self.requested_variant == "auto":
            return device_module.pick_variant(device)
        return self.requested_variant

    def _checkpoint_path(self, variant: str) -> Path:
        name = VARIANT_CHECKPOINTS[variant]
        path = self.models_dir / name
        if not path.exists():
            raise device_module.ModelUnavailableError(
                f"Nedostaje checkpoint {name} u {self.models_dir}. "
                "Pokreni scripts/fetch_models.py (samo build-time)."
            )
        return path

    def _loader(self, variant: str, device: str):
        try:
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor
        except ImportError as error:
            raise device_module.ModelUnavailableError(
                "SAM 2 nije instaliran. Instaliraj ML grupu zavisnosti "
                "(uv sync --extra ml) i preuzmi checkpoint-e."
            ) from error
        config_name = VARIANT_CONFIGS[variant]
        checkpoint = self._checkpoint_path(variant)
        model = build_sam2(config_name, str(checkpoint), device=device)
        return SAM2ImagePredictor(model)

    def load(self) -> None:
        """Load the model, walking the OOM fallback chain if necessary."""
        if self._predictor is not None:
            return
        device = device_module.pick_device(self.requested_device)
        if self.requested_variant == "auto":
            variant = device_module.pick_variant(device)
        else:
            variant = self.requested_variant
        chain = device_module.fallback_variants(variant)
        predictor, resolved_variant, resolved_device = device_module.load_with_fallback(
            self._loader, chain, device
        )
        if resolved_variant != variant or resolved_device != device:
            warnings.warn(
                f"Model je smanjen na {resolved_variant} / {resolved_device} zbog memorije.",
                RuntimeWarning,
                stacklevel=2,
            )
        self._predictor = predictor
        self._resolved_variant = resolved_variant
        self._resolved_device = resolved_device

    # -- inference ------------------------------------------------------------
    def set_image(self, image: np.ndarray) -> None:
        """Compute the image embedding once (RGB, H x W x 3)."""
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("image must be H x W x 3 RGB")
        self.load()
        assert self._predictor is not None
        self._predictor.set_image(image)
        self._image_set = True

    def predict(self, prompt: Prompt, multimask: bool = True) -> SegmentationResult:
        """Run one prediction (specification, 7.3 rules for multimask output)."""
        if prompt.is_empty:
            raise SegmentationError("prompt je prazan: daj tačke, okvir ili --mask-file")
        if self._predictor is None:
            self.load()  # raises ModelUnavailableError when SAM 2 is not installed
        if not self._image_set:
            raise SegmentationError("set_image mora biti pozvan pre predict")
        predictor = self._predictor
        point_coords = np.asarray(prompt.points, dtype=np.float32) if prompt.points else None
        point_labels = np.asarray(prompt.labels, dtype=np.int32) if prompt.labels else None
        box = np.asarray(prompt.box, dtype=np.float32) if prompt.box is not None else None
        masks, scores, _ = predictor.predict(
            point_coords=point_coords,
            point_labels=point_labels,
            box=box,
            multimask_output=multimask,
        )
        candidates = [np.asarray(item, dtype=bool) for item in np.atleast_3d(masks)]
        if not candidates:
            raise SegmentationError("SAM 2 nije vratio nijednu masku")
        if multimask:
            best = int(np.argmax(scores))
            chosen = candidates[best]
        else:
            chosen = candidates[0]
            best = 0
        return SegmentationResult(
            mask=chosen,
            score=float(scores[best]),
            all_candidates=candidates,
        )

    @staticmethod
    def predict_multimask_rule(prompt: Prompt) -> bool:
        """Single point -> multimask; a box (with or without points) -> single mask (7.3)."""
        return len(prompt.points) == 1 and prompt.box is None
