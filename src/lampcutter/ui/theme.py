"""Qt style sheet and colours for the GUI (specification, 12.4)."""

from __future__ import annotations

DARK_THEME = """
QWidget { background: #23232b; color: #e8e8ec; font-size: 13px; }
QMainWindow::separator { background: #3a3a46; width: 3px; }
QGroupBox { border: 1px solid #3d3d4a; border-radius: 4px; margin-top: 8px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; color: #9a9ab0; }
QPushButton {
    background: #3a3a48; border: 1px solid #4b4b5e; border-radius: 4px; padding: 4px 10px;
}
QPushButton:hover { background: #46465a; }
QPushButton:pressed { background: #2f2f3c; }
QPushButton:disabled { color: #77778a; }
QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {
    background: #2b2b36; border: 1px solid #45455a; border-radius: 3px; padding: 2px 4px;
}
QListWidget { background: #2b2b36; border: 1px solid #45455a; }
QProgressBar { border: 1px solid #45455a; border-radius: 3px; text-align: center; }
QProgressBar::chunk { background: #3f7fbf; }
QStatusBar { color: #9a9ab0; }
"""

LIGHT_THEME = """
QWidget { background: #f4f4f6; color: #202028; font-size: 13px; }
QGroupBox { border: 1px solid #c9c9d2; border-radius: 4px; margin-top: 8px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; color: #55556a; }
QPushButton {
    background: #e6e6ec; border: 1px solid #c2c2cf; border-radius: 4px; padding: 4px 10px;
}
QPushButton:hover { background: #dcdce6; }
QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {
    background: #ffffff; border: 1px solid #c2c2cf; border-radius: 3px; padding: 2px 4px;
}
QListWidget { background: #ffffff; border: 1px solid #c2c2cf; }
QProgressBar { border: 1px solid #c2c2cf; border-radius: 3px; text-align: center; }
QProgressBar::chunk { background: #3f7fbf; }
QStatusBar { color: #55556a; }
"""


def theme_stylesheet(dark: bool = True) -> str:
    """Return the QSS for the requested theme."""
    return DARK_THEME if dark else LIGHT_THEME
