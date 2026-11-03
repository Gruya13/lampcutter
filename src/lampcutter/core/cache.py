"""PipelineCache: per-stage hashing and invalidation (specification, 4.3).

Stages and their dependencies:

| stage | depends on |
|---|---|
| S1 image embedding | image (SHA256 of the file bytes) |
| S2 mask | S1 + prompt (or mask_file) |
| S3 clean mask | S2 + mask parameters |
| S4 vectorisation | S3 + scale |
| S5 geometry (inset, tab, kerf) | S4 + base + material + kerf_mode |
| S6 outputs (SVG/PNG) | S5 + slots + decor |

Keys are hashable tuples of digests and frozen values; numpy arrays are never
part of a key (they are digested to SHA256 first, specification 4.2).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import shapely

Stage = Literal["S1", "S2", "S3", "S4", "S5", "S6"]
STAGES: tuple[Stage, ...] = ("S1", "S2", "S3", "S4", "S5", "S6")


def mask_digest(mask: np.ndarray) -> str:
    """SHA256 of a boolean mask (stable across runs)."""
    binary = np.ascontiguousarray(mask.astype(np.uint8))
    return hashlib.sha256(binary.tobytes()).hexdigest()


def polygon_digest(polygon: shapely.Geometry) -> str:
    """SHA256 of rounded polygon coordinates (1e-9 mm); stable for equal geometry."""
    parts: list[bytes] = []
    for item in shapely.get_parts(polygon):
        coords = np.asarray(item.coords if item.geom_type == "LineString" else item.exterior.coords)
        rounded = np.round(coords, 9)
        parts.append(rounded.astype(np.float64).tobytes())
    return hashlib.sha256(b"".join(parts)).hexdigest()


def cut_geometry_digest(cut_geometry: shapely.Geometry) -> str:
    """Stable digest of a cut geometry (nominal + cut path)."""
    if hasattr(cut_geometry, "nominal"):
        nominal = cut_geometry.nominal  # type: ignore[attr-defined]
        cut_path = cut_geometry.cut_path  # type: ignore[attr-defined]
        return hashlib.sha256(
            (polygon_digest(nominal) + polygon_digest(cut_path)).encode("ascii")
        ).hexdigest()
    return polygon_digest(cut_geometry)


def config_digest(**values: Any) -> tuple[tuple[str, str], ...]:
    """Ordered, hashable snapshot of the config values one stage depends on."""
    snapshot: list[tuple[str, str]] = []
    for name in sorted(values):
        value = values[name]
        snapshot.append((name, repr(value)))
    return tuple(snapshot)


def bytes_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class CacheKey:
    """Hashable identity of one stage result."""

    stage: Stage
    parts: tuple[Hashable, ...]


class PipelineCache:
    """Computes each stage once per key; counters make the invalidation testable."""

    def __init__(self) -> None:
        self._store: dict[CacheKey, Any] = {}
        self.computations: Counter[str] = Counter()

    def get(
        self,
        stage: Stage,
        parts: tuple[Hashable, ...],
        factory: Callable[[], Any],
    ) -> Any:
        key = CacheKey(stage, parts)
        if key not in self._store:
            self.computations[stage] += 1
            self._store[key] = factory()
        return self._store[key]

    def clear_from(self, stage: Stage) -> None:
        """Drop the given stage and every later stage (S1 -> clears everything)."""
        start = STAGES.index(stage)
        dropped = [stage_name for stage_name in STAGES[start:] if stage_name in self.computations]
        self._store = {key: value for key, value in self._store.items() if key.stage not in dropped}
        for stage_name in dropped:
            self.computations[stage_name] = 0

    def clear(self) -> None:
        self._store.clear()
        self.computations.clear()

    def __len__(self) -> int:
        return len(self._store)
