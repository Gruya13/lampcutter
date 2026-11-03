"""GUI entry point (specification, 12.4).

Run with `lampcutter gui` or `python -m lampcutter.ui`. PySide6 is an optional
dependency: the CLI works without it, the GUI requires the `gui` extra.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QApplication

from lampcutter.settings import AppSettings
from lampcutter.ui.main_window import MainWindow
from lampcutter.ui.theme import theme_stylesheet


def run_gui(
    argv: list[str] | None = None,
    dark: bool = True,
    initial_image: str | None = None,
) -> int:
    """Create the application, show the main window and enter the event loop."""
    application = QApplication.instance() or QApplication(argv or sys.argv)
    application.setApplicationName("Lampcutter")
    application.setApplicationDisplayName("Lampcutter")
    translator = QTranslator(application)
    application.installTranslator(translator)  # i18n hook; .qm files come in phase 4
    application.setStyleSheet(theme_stylesheet(dark))
    window = MainWindow(AppSettings.load())
    if initial_image:
        window.load_image(initial_image)
    window.show()
    return application.exec()
