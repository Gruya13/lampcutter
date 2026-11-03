"""Project files (`.lampproj`, specification 12.3).

A project stores what the user did in the GUI: the image path, the SAM 2 prompt
or the manual polygon, and the settings/profile references. The segmentation
mask itself is **not** stored (except the manual polygon), because it is a
derived artefact. A link to a `.lamptpl` template keeps the slots and decor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lampcutter.models import Prompt

SCHEMA_VERSION = 1
VALID_REFERENCES = ("height", "width")
VALID_KERF_MODES = ("app", "lightburn")
VALID_INPUT_KINDS = ("mockup", "photo")


@dataclass
class ProjectState:
    """Everything needed to reproduce one export from a project file."""

    image_path: Path | None = None
    prompt: Prompt | None = None
    polygon_px: list[tuple[int, int]] = field(default_factory=list)
    reference: str = "height"
    height_mm: float = 200.0
    material_id: str = "acrylic-3"
    base_id: str | None = "oval-wood"
    kerf_mode: str = "app"
    input_kind: str = "mockup"
    edge_inset_mm: dict[str, float] = field(default_factory=lambda: {"mockup": 0.5, "photo": 0.8})
    simplify_tol_mm: float = 0.03
    template_path: Path | None = None

    def __post_init__(self) -> None:
        if self.reference not in VALID_REFERENCES:
            raise ValueError(f"nepoznata referentna strana {self.reference!r}")
        if self.kerf_mode not in VALID_KERF_MODES:
            raise ValueError(f"nepoznat kerf režim {self.kerf_mode!r}")
        if self.input_kind not in VALID_INPUT_KINDS:
            raise ValueError(f"nepoznata vrsta ulaza {self.input_kind!r}")
        if self.height_mm <= 0:
            raise ValueError("height_mm mora biti pozitivna")


def _prompt_to_dict(prompt: Prompt) -> dict:
    return {
        "points": [list(point) for point in prompt.points],
        "labels": list(prompt.labels),
        "box": list(prompt.box) if prompt.box is not None else None,
    }


def _prompt_from_dict(data: dict) -> Prompt:
    box = data.get("box")
    return Prompt(
        points=tuple(tuple(point) for point in data.get("points", [])),
        labels=tuple(int(label) for label in data.get("labels", [])),
        box=tuple(int(value) for value in box) if box is not None else None,
    )


def _path_to_json(path: Path | None, base_dir: Path) -> str | None:
    if path is None:
        return None
    path = Path(path)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    try:
        return str(path.resolve().relative_to(base_dir.resolve()))
    except ValueError:
        return str(path.resolve())


def _path_from_json(value: str | None, base_dir: Path) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def project_to_dict(state: ProjectState, base_dir: Path | None = None) -> dict:
    """Serialise a project; paths inside the project folder become relative."""
    directory = Path(base_dir) if base_dir is not None else Path.cwd()
    return {
        "schema": SCHEMA_VERSION,
        "image_path": _path_to_json(state.image_path, directory),
        "prompt": _prompt_to_dict(state.prompt) if state.prompt is not None else None,
        "polygon_px": [list(point) for point in state.polygon_px],
        "reference": state.reference,
        "height_mm": state.height_mm,
        "material_id": state.material_id,
        "base_id": state.base_id,
        "kerf_mode": state.kerf_mode,
        "input_kind": state.input_kind,
        "edge_inset_mm": dict(state.edge_inset_mm),
        "simplify_tol_mm": state.simplify_tol_mm,
        "template_path": _path_to_json(state.template_path, directory),
    }


def project_from_dict(data: dict, base_dir: Path | None = None) -> ProjectState:
    """Rebuild a project; unknown schema versions are rejected."""
    if int(data.get("schema", 0)) != SCHEMA_VERSION:
        raise ValueError(f"nepoznata verzija šeme projekta: {data.get('schema')!r}")
    directory = Path(base_dir) if base_dir is not None else Path.cwd()
    prompt_data = data.get("prompt")
    return ProjectState(
        image_path=_path_from_json(data.get("image_path"), directory),
        prompt=_prompt_from_dict(prompt_data) if prompt_data else None,
        polygon_px=[tuple(int(value) for value in point) for point in data.get("polygon_px", [])],
        reference=data.get("reference", "height"),
        height_mm=float(data.get("height_mm", 200.0)),
        material_id=data.get("material_id", "acrylic-3"),
        base_id=data.get("base_id", "oval-wood"),
        kerf_mode=data.get("kerf_mode", "app"),
        input_kind=data.get("input_kind", "mockup"),
        edge_inset_mm={
            str(key): float(value)
            for key, value in data.get("edge_inset_mm", {"mockup": 0.5, "photo": 0.8}).items()
        },
        simplify_tol_mm=float(data.get("simplify_tol_mm", 0.03)),
        template_path=_path_from_json(data.get("template_path"), directory),
    )


def save_project(state: ProjectState, path: Path | str) -> Path:
    """Write a `.lampproj` file (paths relative to the project file)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = project_to_dict(state, base_dir=path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_project(path: Path | str) -> ProjectState:
    """Read a `.lampproj` file."""
    path = Path(path)
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return project_from_dict(data, base_dir=path.parent)
