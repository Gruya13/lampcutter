"""Translation loading (specification, 0.2.8 and 12.4).

Serbian is the source language, so the GUI needs no translation file to run.
Other languages are added as `resources/translations/lampcutter_<lang>.qm`;
when a file is missing the source strings are used unchanged.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTranslator


def translations_dir() -> Path:
    """Directory with `.qm` files (repository resource folder, if present)."""
    return Path(__file__).resolve().parents[3] / "resources" / "translations"


def available_languages() -> list[str]:
    """Languages that have a compiled translation file."""
    directory = translations_dir()
    if not directory.is_dir():
        return []
    return sorted(
        path.stem.removeprefix("lampcutter_") for path in directory.glob("lampcutter_*.qm")
    )


def load_translations(app, language: str | None = None) -> QTranslator:
    """Load and install a translation; returns the translator (empty on fallback)."""
    translator = QTranslator(app)
    if language is not None:
        candidate = translations_dir() / f"lampcutter_{language}.qm"
        if candidate.is_file():
            translator.load(str(candidate))
    app.installTranslator(translator)
    return translator
