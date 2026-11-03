"""User settings and profiles (specification, sections 6.2 and 6.3).

Profiles live in the platform configuration directory as JSON and are editable
from the GUI. Values shipped here are illustrative (PROVISIONAL) and are
replaced by calibration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from lampcutter.config import Config
from lampcutter.models import BaseProfile, MaterialProfile

APP_NAME = "lampcutter"

# PROVISIONAL (specification, 6.2): illustrative values, real ones from calibration.
DEFAULT_MATERIALS: tuple[MaterialProfile, ...] = (
    MaterialProfile(
        id="acrylic-3",
        name="Akril providni 3 mm",
        thickness_mm=3.0,
        kerf_mm=0.18,
        min_feature_mm=1.5,
    ),
    MaterialProfile(
        id="acrylic-5",
        name="Akril providni 5 mm",
        thickness_mm=5.0,
        kerf_mm=0.22,
        min_feature_mm=2.0,
    ),
)

# PROVISIONAL (specification, 6.3): illustrative values, real ones from the user.
DEFAULT_BASES: tuple[BaseProfile, ...] = (
    BaseProfile(
        id="oval-wood",
        name="Ovalna drvena",
        slot_length_mm=80.0,
        slot_thickness_mm=3.4,
        slot_dimensions="measured",
        tab_width_mm=78.0,
        tab_height_mm=8.0,
    ),
)


def config_dir() -> Path:
    """Directory where user profiles and settings are stored."""
    return Path(user_config_dir(APP_NAME))


def materials_path() -> Path:
    return config_dir() / "materials.json"


def bases_path() -> Path:
    return config_dir() / "bases.json"


def _load_json_list(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    return data


def load_materials(path: Path | None = None) -> list[MaterialProfile]:
    """Load material profiles; fall back to the built-in defaults."""
    raw = _load_json_list(path if path is not None else materials_path())
    if raw is None:
        return list(DEFAULT_MATERIALS)
    return [MaterialProfile(**item) for item in raw]


def load_bases(path: Path | None = None) -> list[BaseProfile]:
    """Load base profiles; fall back to the built-in defaults."""
    raw = _load_json_list(path if path is not None else bases_path())
    if raw is None:
        return list(DEFAULT_BASES)
    return [BaseProfile(**item) for item in raw]


def _dump_json_list(path: Path, items: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump([item.__dict__ for item in items], handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def save_materials(materials: list[MaterialProfile], path: Path | None = None) -> Path:
    target = path if path is not None else materials_path()
    _dump_json_list(target, materials)
    return target


def save_bases(bases: list[BaseProfile], path: Path | None = None) -> Path:
    target = path if path is not None else bases_path()
    _dump_json_list(target, bases)
    return target


def find_material(materials: list[MaterialProfile], material_id: str) -> MaterialProfile:
    """Return the profile with the given id or raise a clear error."""
    for material in materials:
        if material.id == material_id:
            return material
    known = ", ".join(item.id for item in materials)
    raise KeyError(f"Nepoznat materijal {material_id!r}. Dostupni: {known}")


def find_base(bases: list[BaseProfile], base_id: str) -> BaseProfile:
    """Return the base profile with the given id or raise a clear error."""
    for base in bases:
        if base.id == base_id:
            return base
    known = ", ".join(item.id for item in bases)
    raise KeyError(f"Nepoznata baza {base_id!r}. Dostupne: {known}")


@dataclass
class AppSettings:
    """Everything the application needs at start-up."""

    config: Config = field(default_factory=Config)
    materials: list[MaterialProfile] = field(default_factory=lambda: list(DEFAULT_MATERIALS))
    bases: list[BaseProfile] = field(default_factory=lambda: list(DEFAULT_BASES))

    @classmethod
    def load(cls, config_path: Path | None = None) -> AppSettings:
        has_file = config_path is not None and Path(config_path).exists()
        config = Config.from_toml(config_path) if has_file else Config()
        return cls(config=config, materials=load_materials(), bases=load_bases())

    def material(self, material_id: str) -> MaterialProfile:
        return find_material(self.materials, material_id)

    def base(self, base_id: str) -> BaseProfile:
        return find_base(self.bases, base_id)
