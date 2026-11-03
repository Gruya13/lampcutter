"""Main window: canvas, panels and background pipeline runs (specification, 12.1-12.4)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from lampcutter.config import Config
from lampcutter.core import geometry
from lampcutter.core.pipeline import PipelineResult, run_pipeline
from lampcutter.models import BaseProfile, MaterialProfile
from lampcutter.settings import AppSettings
from lampcutter.ui.canvas import Canvas
from lampcutter.ui.panels import (
    BasePanel,
    ContourPanel,
    ElementsPanel,
    MaterialPanel,
    SizePanel,
)
from lampcutter.ui.workers import Debouncer, TaskRunner


class MainWindow(QMainWindow):
    """GUI skeleton: image canvas, side panels and the export pipeline in workers."""

    def __init__(self, settings: AppSettings | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings or AppSettings.load()
        self.setWindowTitle("Lampcutter")
        self.resize(1500, 950)
        self.setAcceptDrops(True)

        self.image_path: Path | None = None
        self.last_result: PipelineResult | None = None
        self.last_error: str | None = None
        self._cancel_requested = False

        self.canvas = Canvas()
        self.size_panel = SizePanel()
        self.material_panel = MaterialPanel(self.settings.materials)
        self.base_panel = BasePanel(self.settings.bases)
        self.contour_panel = ContourPanel()
        self.elements_panel = ElementsPanel()

        side = QWidget()
        side_layout = QVBoxLayout(side)
        for panel in (
            self.size_panel,
            self.material_panel,
            self.base_panel,
            self.contour_panel,
            self.elements_panel,
        ):
            side_layout.addWidget(panel)
        side_layout.addStretch(1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.canvas)
        splitter.addWidget(side)
        splitter.setSizes([1050, 430])

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.cancel_button = QPushButton("Otkaži")
        self.cancel_button.setEnabled(False)
        self.export_button = QPushButton("Izvezi")
        bottom = QHBoxLayout()
        bottom.addWidget(self.progress, 1)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.export_button)
        bottom_widget = QWidget()
        bottom_widget.setLayout(bottom)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(splitter, 1)
        layout.addWidget(bottom_widget)
        self.setCentralWidget(central)

        self._build_menu()
        self.statusBar().showMessage("Učitaj sliku (Ctrl+O ili prevuci fajl na platno).")
        self.runner = TaskRunner(self)
        self.debouncer = Debouncer(150, self)
        self._connect_signals()
        self._update_clearance()

    # ------------------------------------------------------------------ setup
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Datoteka")
        open_action = QAction("Otvori sliku…", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_image_dialog)
        file_menu.addAction(open_action)
        export_action = QAction("Izvezi", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.export)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        quit_action = QAction("Izlaz", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        edit_menu = self.menuBar().addMenu("&Uredi")
        undo_action = QAction("Poništi", self)
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        undo_action.triggered.connect(self.undo)
        edit_menu.addAction(undo_action)
        clear_action = QAction("Očisti prompt", self)
        clear_action.triggered.connect(self.clear_prompt)
        edit_menu.addAction(clear_action)

        mode_menu = self.menuBar().addMenu("&Režim")
        prompt_mode = QAction("Prompt (tačke/okvir)", self)
        prompt_mode.triggered.connect(lambda: self.canvas.set_mode(Canvas.MODE_PROMPT))
        mode_menu.addAction(prompt_mode)
        polygon_mode = QAction("Poligon alat", self)
        polygon_mode.triggered.connect(lambda: self.canvas.set_mode(Canvas.MODE_POLYGON))
        mode_menu.addAction(polygon_mode)

    def _connect_signals(self) -> None:
        self.canvas.prompt_point_added.connect(lambda *_: self._on_interaction())
        self.canvas.box_selected.connect(lambda *_: self._on_interaction())
        self.canvas.polygon_finished.connect(lambda *_: self._on_interaction())
        self.canvas.image_loaded.connect(lambda *_: self._on_interaction())
        self.size_panel.size_changed.connect(lambda *_: self._on_interaction())
        self.material_panel.material_changed.connect(lambda *_: self._on_interaction())
        self.base_panel.base_changed.connect(lambda *_: self._on_settings_changed())
        self.contour_panel.contour_changed.connect(lambda *_: self._on_settings_changed())
        self.elements_panel.mode_changed.connect(self._on_element_mode)
        self.cancel_button.clicked.connect(self.cancel)
        self.export_button.clicked.connect(self.export)

    # ------------------------------------------------------------------ state
    def current_config(self) -> Config:
        cfg = Config()
        values = self.contour_panel.values()
        cfg.kerf_mode = values["kerf_mode"]
        cfg.simplify_tol_mm = values["simplify_tol_mm"]
        cfg.edge_inset_mm = {**cfg.edge_inset_mm, values["input_kind"]: values["edge_inset_mm"]}
        return cfg

    def current_material(self) -> MaterialProfile:
        material_id = self.material_panel.current_material_id()
        for material in self.settings.materials:
            if material.id == material_id:
                return material
        return self.settings.materials[0]

    def current_base(self) -> BaseProfile | None:
        base_id = self.base_panel.current_base_id()
        for base in self.settings.bases:
            if base.id == base_id:
                return base
        return None

    def current_input_kind(self) -> str:
        return str(self.contour_panel.values()["input_kind"])

    def _update_clearance(self) -> None:
        base = self.current_base()
        if base is None:
            return
        material = self.current_material()
        clearance = geometry.slot_clearance(base, material)
        self.base_panel.set_clearance(
            clearance.planar_clearance_mm, clearance.thickness_clearance_mm
        )

    # ---------------------------------------------------------------- actions
    def load_image(self, path: str | Path) -> None:
        path = Path(path)
        try:
            self.canvas.set_image(path)
        except Exception as error:  # shown to the user
            self._show_error(f"Ne mogu da učitam sliku: {error}")
            return
        self.image_path = path
        self.last_result = None
        self.elements_panel.set_elements([], [])
        self.statusBar().showMessage(f"Učitano: {path.name}")

    def open_image_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Otvori sliku", "", "Slike (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            self.load_image(path)

    def _on_interaction(self) -> None:
        if self.image_path is not None:
            self.debouncer.schedule(self.recompute)

    def _on_settings_changed(self) -> None:
        self._update_clearance()
        self._on_interaction()

    def recompute(self) -> None:
        """Start the pipeline in a worker with the current prompt/polygon."""
        if self.image_path is None:
            self.statusBar().showMessage("Prvo učitaj sliku.")
            return
        polygon = self._finished_polygon_px()
        if polygon is None and self.canvas.prompt_builder.is_empty:
            self.statusBar().showMessage("Dodaj tačku, okvir ili poligon.")
            return
        self._cancel_requested = False
        self.progress.setValue(0)
        self.cancel_button.setEnabled(True)
        self.statusBar().showMessage("Obrađujem…")
        self.runner.run(
            self._run_job,
            on_finished=self._on_result,
            on_failed=self._on_failed,
            on_progress=self._on_progress,
        )

    def _finished_polygon_px(self) -> list[tuple[int, int]] | None:
        if self.canvas.polygon_tool.closed and len(self.canvas.polygon_tool.points) >= 3:
            return [(round(x), round(y)) for x, y in self.canvas.polygon_tool.points]
        return None

    def _run_job(self, progress=None) -> PipelineResult:
        polygon = self._finished_polygon_px()
        prompt = None if polygon is not None else self.canvas.prompt_builder.to_prompt()
        return run_pipeline(
            self.image_path,
            prompt=prompt,
            polygon_px=polygon,
            config=self.current_config(),
            material=self.current_material(),
            base=self.current_base(),
            input_kind=self.current_input_kind(),
            height_mm=self.size_panel.value_mm(),
            reference=self.size_panel.reference(),
            out_dir=Path("izlaz") / "gui",
            progress=progress,
            cancel=lambda: self._cancel_requested,
        )

    def _on_progress(self, stage: str, fraction: float) -> None:
        self.progress.setValue(int(max(0.0, min(1.0, fraction)) * 100))
        self.statusBar().showMessage(stage)

    def _on_result(self, result: PipelineResult) -> None:
        self.last_result = result
        self.progress.setValue(100)
        self.cancel_button.setEnabled(False)
        self.canvas.set_mask(result.mask_clean)
        self.canvas.set_overlay_geometry([result.cut_geometry.cut_path], result.scale.mm_per_px)
        if result.clearance is not None:
            self.base_panel.set_clearance(
                result.clearance.planar_clearance_mm,
                result.clearance.thickness_clearance_mm,
            )
        self.statusBar().showMessage(f"Izvezeno: {result.svg_path}")

    def _on_failed(self, message: str) -> None:
        self.progress.setValue(0)
        self.cancel_button.setEnabled(False)
        self._show_error(message)

    def export(self) -> None:
        self.recompute()

    def cancel(self) -> None:
        self._cancel_requested = True
        self.runner.cancel()
        self.cancel_button.setEnabled(False)
        self.statusBar().showMessage("Otkazano")

    def undo(self) -> None:
        if self.canvas.undo_last():
            self._on_interaction()

    def clear_prompt(self) -> None:
        self.canvas.clear_prompt()
        self.statusBar().showMessage("Prompt očišćen")

    def _on_element_mode(self, element_id: str, mode: str) -> None:
        self.statusBar().showMessage(f"Element {element_id}: režim {mode} (čuva se u Fazi 3)")

    def _show_error(self, message: str) -> None:
        """Report an error through the status bar.

        A modal dialog would block headless tests and a background export; the
        error is kept on `last_error` for callers and the UI shows it in the
        status bar instead.
        """
        self.last_error = message
        self.statusBar().showMessage(f"Greška: {message}")

    # -------------------------------------------------------------- drag&drop
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                self.load_image(local)
                break

    def closeEvent(self, event) -> None:
        self.runner.cancel()
        self.runner.wait(3000)
        super().closeEvent(event)
