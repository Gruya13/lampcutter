"""Main window: canvas, panels, projects and background pipeline runs (spec 12)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import shapely
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
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
from lampcutter.core import compose, geometry, mask_ops, project
from lampcutter.core import slots as slots_module
from lampcutter.core.pipeline import PipelineResult, revectorize_mask, run_pipeline
from lampcutter.models import BaseProfile, DecorElement, LampTemplate, MaterialProfile, PhotoSlot
from lampcutter.settings import AppSettings, save_bases, save_materials
from lampcutter.ui.canvas import Canvas
from lampcutter.ui.dialogs import BaseEditorDialog, MaterialEditorDialog
from lampcutter.ui.panels import (
    BasePanel,
    BrushPanel,
    ContourPanel,
    ElementsPanel,
    MaterialPanel,
    SizePanel,
)
from lampcutter.ui.workers import Debouncer, TaskRunner

PROJECT_FILTER = "Lampcutter projekat (*.lampproj)"
TEMPLATE_FILTER = "Lampcutter šablon (*.lamptpl)"


class MainWindow(QMainWindow):
    """GUI: image canvas, side panels, project/template files and the export pipeline."""

    def __init__(self, settings: AppSettings | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings or AppSettings.load()
        self.setWindowTitle("Lampcutter")
        self.resize(1500, 950)
        self.setAcceptDrops(True)

        self.image_path: Path | None = None
        self.last_result: PipelineResult | None = None
        self.last_export: compose.ExportResult | None = None
        self.last_error: str | None = None
        self.template: LampTemplate | None = None
        self.project_path: Path | None = None
        self.template_path: Path | None = None
        self.brush_mask: np.ndarray | None = None
        self.brush_history: list[np.ndarray] = []
        self._cancel_requested = False

        self.canvas = Canvas()
        self.size_panel = SizePanel()
        self.material_panel = MaterialPanel(self.settings.materials)
        self.base_panel = BasePanel(self.settings.bases)
        self.contour_panel = ContourPanel()
        self.elements_panel = ElementsPanel()
        self.brush_panel = BrushPanel()
        self.brush_panel.set_from_config(self.current_config_for_brush())

        side = QWidget()
        side_layout = QVBoxLayout(side)
        for panel in (
            self.size_panel,
            self.material_panel,
            self.base_panel,
            self.contour_panel,
            self.brush_panel,
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
        self.save_project_button = QPushButton("Sačuvaj projekat")
        bottom = QHBoxLayout()
        bottom.addWidget(self.progress, 1)
        bottom.addWidget(self.save_project_button)
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
        self.retouch_debouncer = Debouncer(250, self)
        self._connect_signals()
        self._update_clearance()

    # ------------------------------------------------------------------ setup
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Datoteka")
        self._add_action(
            file_menu, "Otvori sliku…", self.open_image_dialog, QKeySequence.StandardKey.Open
        )
        self._add_action(file_menu, "Otvori projekat…", self.open_project_dialog, "Ctrl+Shift+O")
        self._add_action(file_menu, "Sačuvaj projekat", self.save_project, "Ctrl+S")
        self._add_action(
            file_menu, "Sačuvaj projekat kao…", self.save_project_dialog, "Ctrl+Shift+S"
        )
        file_menu.addSeparator()
        self._add_action(file_menu, "Otvori šablon…", self.open_template_dialog)
        self._add_action(file_menu, "Sačuvaj šablon…", self.save_template_dialog)
        file_menu.addSeparator()
        self._add_action(file_menu, "Izvezi", self.export, "Ctrl+E")
        self._add_action(file_menu, "Izlaz", self.close, QKeySequence.StandardKey.Quit)

        edit_menu = self.menuBar().addMenu("&Uredi")
        self._add_action(edit_menu, "Poništi", self.undo, QKeySequence.StandardKey.Undo)
        self._add_action(edit_menu, "Očisti prompt", self.clear_prompt)

        mode_menu = self.menuBar().addMenu("&Režim")
        self._add_action(
            mode_menu,
            "Prompt (tačke/okvir)",
            lambda: self.canvas.set_mode(Canvas.MODE_PROMPT),
        )
        self._add_action(
            mode_menu,
            "Poligon alat",
            lambda: self.canvas.set_mode(Canvas.MODE_POLYGON),
        )
        self._add_action(
            mode_menu,
            "Četkica (retuš maske)",
            lambda: self.canvas.set_mode(Canvas.MODE_BRUSH),
        )

        element_menu = self.menuBar().addMenu("&Elementi")
        self._add_action(
            element_menu,
            "Dodaj slot iz poligona",
            lambda: self.add_element_from_polygon("slot"),
        )
        self._add_action(
            element_menu,
            "Dodaj gravuru iz poligona",
            lambda: self.add_element_from_polygon("decor", "engrave"),
        )
        self._add_action(
            element_menu,
            "Dodaj štampu iz poligona",
            lambda: self.add_element_from_polygon("decor", "print"),
        )
        self._add_action(element_menu, "Ukloni izabrani element", self.remove_selected_element)
        self._add_action(element_menu, "Očisti elemente", self.clear_elements)

    def _add_action(self, menu, text: str, slot, shortcut=None) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(lambda _checked=False: slot())
        menu.addAction(action)
        return action

    def _connect_signals(self) -> None:
        self.canvas.prompt_point_added.connect(lambda *_: self._on_interaction())
        self.canvas.box_selected.connect(lambda *_: self._on_interaction())
        self.canvas.polygon_finished.connect(lambda *_: self._on_interaction())
        self.canvas.image_loaded.connect(lambda *_: self._on_interaction())
        self.size_panel.size_changed.connect(lambda *_: self._on_interaction())
        self.size_panel.size_changed.connect(lambda *_: self._refresh_computed())
        self.material_panel.material_changed.connect(lambda *_: self._on_interaction())
        self.material_panel.edit_requested.connect(self._edit_material)
        self.base_panel.base_changed.connect(lambda *_: self._on_settings_changed())
        self.base_panel.edit_requested.connect(self._edit_base)
        self.contour_panel.contour_changed.connect(lambda *_: self._on_settings_changed())
        self.elements_panel.mode_changed.connect(self._on_element_mode)
        self.canvas.brush_stroke_finished.connect(self._on_brush_stroke)
        self.brush_panel.brush_changed.connect(self._on_brush_changed)
        self.brush_panel.undo_requested.connect(self.undo)
        self.cancel_button.clicked.connect(self.cancel)
        self.export_button.clicked.connect(self.export)
        self.save_project_button.clicked.connect(self.save_project)

    # ------------------------------------------------------------------ state
    def current_config_for_brush(self) -> Config:
        return Config()

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
        clearance = geometry.slot_clearance(base, self.current_material())
        self.base_panel.set_clearance(
            clearance.planar_clearance_mm, clearance.thickness_clearance_mm
        )

    def _refresh_computed(self) -> None:
        if self.last_result is not None:
            height_mm = self.last_result.scale.height_mm
            tab = self.current_base().tab_height_mm if self.current_base() else 0.0
            self.size_panel.set_computed(
                self.last_result.scale.width_mm, height_mm, height_mm + tab
            )

    # ---------------------------------------------------------------- profiles
    def _edit_material(self) -> None:
        material = self.current_material()
        dialog = MaterialEditorDialog(material, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.edited_material()
        self.settings.materials = [
            updated if item.id == material.id else item for item in self.settings.materials
        ]
        try:
            save_materials(self.settings.materials)
        except OSError as error:  # pragma: no cover - filesystem dependent
            self._show_error(f"Ne mogu da sačuvam profil materijala: {error}")
        self.material_panel.set_materials(self.settings.materials)
        self.material_panel.select_material(updated.id)
        self._update_clearance()
        self.statusBar().showMessage(
            f"Materijal {updated.id}: kerf {updated.kerf_mm:g} mm (važi za sledeći izvoz)"
        )
        self._on_interaction()

    def _edit_base(self) -> None:
        base = self.current_base()
        if base is None:
            return
        dialog = BaseEditorDialog(base, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.edited_base()
        self.settings.bases = [
            updated if item.id == base.id else item for item in self.settings.bases
        ]
        try:
            save_bases(self.settings.bases)
        except OSError as error:  # pragma: no cover - filesystem dependent
            self._show_error(f"Ne mogu da sačuvam profil postolja: {error}")
        self.base_panel.set_bases(self.settings.bases)
        self.base_panel.select_base(updated.id)
        self._update_clearance()
        self.statusBar().showMessage(f"Postolje {updated.id}: sačuvano (važi za sledeći izvoz)")
        self._on_interaction()

    # ----------------------------------------------------------------- actions
    def load_image(self, path: str | Path) -> None:
        path = Path(path)
        try:
            self.canvas.set_image(path)
        except Exception as error:
            self._show_error(f"Ne mogu da učitam sliku: {error}")
            return
        self.image_path = path
        self.last_result = None
        self.template = None
        self.brush_mask = None
        self.brush_history = []
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
        self._apply_result(result, reset_brush_history=True)

    def _on_retouch_result(self, result: PipelineResult) -> None:
        self._apply_result(result, reset_brush_history=False)
        self.statusBar().showMessage("Retuš maske primenjen")

    def _apply_result(self, result: PipelineResult, *, reset_brush_history: bool) -> None:
        self.last_result = result
        self.brush_mask = result.mask_clean.copy() if result.mask_clean is not None else None
        if reset_brush_history:
            self.brush_history = []
        self.progress.setValue(100)
        self.cancel_button.setEnabled(False)
        self.canvas.set_mask(result.mask_clean)
        self.canvas.set_overlay_geometry([result.cut_geometry.cut_path], result.scale.mm_per_px)
        if result.clearance is not None:
            self.base_panel.set_clearance(
                result.clearance.planar_clearance_mm,
                result.clearance.thickness_clearance_mm,
            )
        self._ensure_template()
        self._refresh_elements()
        self._refresh_computed()
        self.statusBar().showMessage(f"Geometrija: {result.svg_path}")
        if self.template is not None and (self.template.slots or self.template.decor):
            self.runner.run(
                compose.export_bundle,
                self.template,
                Path("izlaz") / "gui",
                self.current_config(),
                on_finished=self._on_export_done,
                on_failed=self._on_export_failed,
            )

    def _on_export_done(self, export_result: compose.ExportResult) -> None:
        self.last_export = export_result
        message = f"Izvezeno: {export_result.svg_path}"
        if export_result.print_sheet_path is not None:
            message += f" + {export_result.print_sheet_path.name}"
        self.statusBar().showMessage(message)
        for warning in export_result.warnings:
            self.statusBar().showMessage(f"Upozorenje: {warning}", 8000)

    def _on_export_failed(self, message: str) -> None:
        self._show_error(f"Izvoz štampe nije uspeo: {message}")

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
        if self.canvas.mode == Canvas.MODE_BRUSH and self.brush_history:
            self.brush_mask = self.brush_history.pop()
            self.canvas.set_mask(self.brush_mask)
            self._revectorize()
            return
        if self.canvas.undo_last():
            self._on_interaction()

    def clear_prompt(self) -> None:
        self.canvas.clear_prompt()
        self.statusBar().showMessage("Prompt očišćen")

    # -------------------------------------------------------- project / template
    def current_project_state(self) -> project.ProjectState:
        contour = self.contour_panel.values()
        cfg = self.current_config()
        edge_inset = dict(cfg.edge_inset_mm)
        edge_inset[contour["input_kind"]] = contour["edge_inset_mm"]
        prompt = (
            self.canvas.prompt_builder.to_prompt()
            if not self.canvas.prompt_builder.is_empty
            else None
        )
        polygon = (
            [(round(x), round(y)) for x, y in self.canvas.polygon_tool.points]
            if self.canvas.polygon_tool.closed
            else []
        )
        return project.ProjectState(
            image_path=self.image_path,
            prompt=prompt,
            polygon_px=polygon,
            reference=self.size_panel.reference(),
            height_mm=self.size_panel.value_mm(),
            material_id=self.current_material().id,
            base_id=self.current_base().id if self.current_base() else None,
            kerf_mode=contour["kerf_mode"],
            input_kind=contour["input_kind"],
            edge_inset_mm=edge_inset,
            simplify_tol_mm=contour["simplify_tol_mm"],
            template_path=self.template_path,
        )

    def apply_project_state(self, state: project.ProjectState) -> None:
        if state.image_path is not None and state.image_path.exists():
            self.load_image(state.image_path)
        if state.prompt is not None:
            self.canvas.load_prompt(state.prompt)
        if state.polygon_px:
            self.canvas.load_polygon(state.polygon_px)
        self.size_panel.set_reference(state.reference)
        self.size_panel.set_value_mm(state.height_mm)
        self.material_panel.select_material(state.material_id)
        self.base_panel.select_base(state.base_id)
        self.contour_panel.set_values(
            {
                "input_kind": state.input_kind,
                "kerf_mode": state.kerf_mode,
                "simplify_tol_mm": state.simplify_tol_mm,
                "edge_inset_mm": state.edge_inset_mm.get(
                    state.input_kind, self.contour_panel.edge_inset.value()
                ),
            }
        )
        if state.template_path is not None and state.template_path.exists():
            self._load_template_file(state.template_path)
        self._update_clearance()

    def save_project(self) -> None:
        if self.project_path is None:
            self.save_project_dialog()
            return
        self._write_project(self.project_path)

    def save_project_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Sačuvaj projekat", "", PROJECT_FILTER)
        if not path:
            return
        if not path.endswith(".lampproj"):
            path += ".lampproj"
        self._write_project(Path(path))

    def _write_project(self, path: Path) -> None:
        state = self.current_project_state()
        project.save_project(state, path)
        self.project_path = path
        self.statusBar().showMessage(f"Projekat sačuvan: {path}")

    def open_project_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Otvori projekat", "", PROJECT_FILTER)
        if path:
            self.open_project(Path(path))

    def open_project(self, path: Path) -> None:
        try:
            state = project.load_project(path)
        except (OSError, ValueError) as error:
            self._show_error(f"Ne mogu da otvorim projekat: {error}")
            return
        self.apply_project_state(state)
        self.project_path = Path(path)
        self.statusBar().showMessage(f"Projekat otvoren: {path}")

    def save_template_dialog(self) -> None:
        self._ensure_template()
        if self.template is None:
            self._show_error("Prvo izvezi geometriju (Izvezi), pa sačuvaj šablon.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Sačuvaj šablon", "", TEMPLATE_FILTER)
        if not path:
            return
        if not path.endswith(".lamptpl"):
            path += ".lamptpl"
        slots_module.save_template(self.template, path)
        self.template_path = Path(path)
        self.statusBar().showMessage(f"Šablon sačuvan: {path}")

    def open_template_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Otvori šablon", "", TEMPLATE_FILTER)
        if path:
            self._load_template_file(Path(path))

    def _load_template_file(self, path: Path) -> None:
        try:
            self.template = slots_module.load_template(path)
        except (OSError, ValueError) as error:
            self._show_error(f"Ne mogu da otvorim šablon: {error}")
            return
        self.template_path = Path(path)
        self._refresh_elements()
        self.statusBar().showMessage(f"Šablon otvoren: {path}")

    # -------------------------------------------------------------- elements
    def _ensure_template(self) -> None:
        """Build the current template from the last result and the existing elements."""
        if self.last_result is None:
            return
        existing_slots = self.template.slots if self.template is not None else []
        existing_decor = self.template.decor if self.template is not None else []
        self.template = LampTemplate(
            outline=self.last_result.cut_geometry,
            slots=existing_slots,
            decor=existing_decor,
            base=self.current_base() or self.settings.bases[0],
            material=self.current_material(),
            scale=self.last_result.scale,
            input_kind=self.current_input_kind(),
        )

    def _mm_per_px(self) -> float | None:
        if self.last_result is not None:
            return self.last_result.scale.mm_per_px
        if self.template is not None:
            return self.template.scale.mm_per_px
        return None

    def _refresh_elements(self) -> None:
        slots = self.template.slots if self.template is not None else []
        decor = self.template.decor if self.template is not None else []
        self.elements_panel.set_elements(slots, decor)
        mm_per_px = self._mm_per_px()
        if mm_per_px:
            self.canvas.set_slots([slot.polygon_mm for slot in slots], mm_per_px)
            self.canvas.set_decor([element.polygon_mm for element in decor], mm_per_px)

    def _polygon_mm(self) -> shapely.Polygon | None:
        polygon_px = self._finished_polygon_px()
        mm_per_px = self._mm_per_px()
        if polygon_px is None or mm_per_px is None:
            return None
        return shapely.Polygon([(x * mm_per_px, y * mm_per_px) for x, y in polygon_px])

    def add_element_from_polygon(self, kind: str, decor_mode: str = "engrave") -> None:
        """Turn the finished manual polygon into a slot or a decor element."""
        self._ensure_template()
        if self.template is None or self.last_result is None:
            self._show_error("Prvo izvezi geometriju (Izvezi), pa dodaj element iz poligona.")
            return
        polygon = self._polygon_mm()
        if polygon is None:
            self._show_error("Nacrtaj i završi poligon (desni klik), pa dodaj element.")
            return
        if kind == "slot":
            element_id = f"slot-{len(self.template.slots) + 1}"
            self.template.slots.append(
                PhotoSlot(id=element_id, polygon_mm=polygon, source="manual")
            )
        elif kind == "decor":
            element_id = f"decor-{len(self.template.decor) + 1}"
            self.template.decor.append(
                DecorElement(
                    id=element_id,
                    polygon_mm=polygon,
                    source="manual",
                    mode=decor_mode if decor_mode in ("engrave", "print", "none") else "engrave",
                )
            )
        else:
            raise ValueError(f"nepoznata vrsta elementa {kind!r}")
        self.canvas.polygon_tool.reset()
        self.canvas._redraw_polygon()
        self._refresh_elements()
        self.statusBar().showMessage(f"Dodat element {element_id}")

    def remove_selected_element(self) -> None:
        if self.template is None:
            return
        current = self.elements_panel.current_element()
        if current is None:
            self.statusBar().showMessage("Izaberi element u listi.")
            return
        kind, element_id = current
        if kind == "slot":
            self.template.slots = [slot for slot in self.template.slots if slot.id != element_id]
        else:
            self.template.decor = [
                element for element in self.template.decor if element.id != element_id
            ]
        self._refresh_elements()
        self.statusBar().showMessage(f"Uklonjen element {element_id}")

    def clear_elements(self) -> None:
        if self.template is not None:
            self.template.slots = []
            self.template.decor = []
        self._refresh_elements()
        self.statusBar().showMessage("Elementi očišćeni")

    def _on_element_mode(self, element_id: str, mode: str) -> None:
        if self.template is None:
            return
        for element in self.template.decor:
            if element.id == element_id:
                element.mode = mode if mode in ("engrave", "print", "none") else element.mode
                self._refresh_elements()
                self.statusBar().showMessage(f"Element {element_id}: režim {mode}")
                return

    # ------------------------------------------------------------------ brush
    def _on_brush_changed(self, radius_px: int, add: bool) -> None:
        self.canvas.set_brush(radius_px, add)

    def _on_brush_stroke(self, points: list, add: bool, radius_px: int) -> None:
        """Apply one brush stroke to the mask and re-vectorise in a worker."""
        if self.brush_mask is None or self.image_path is None:
            self.statusBar().showMessage("Prvo izvezi geometriju, pa retuširaj masku.")
            return
        updated = mask_ops.paint_stroke(self.brush_mask, points, radius_px, add=add)
        if np.array_equal(updated, self.brush_mask):
            return
        self.brush_history.append(self.brush_mask)
        if len(self.brush_history) > 10:
            self.brush_history.pop(0)
        self.brush_mask = updated
        self.canvas.set_mask(updated)
        self.retouch_debouncer.schedule(self._revectorize)

    def _revectorize(self) -> None:
        if self.brush_mask is None or self.image_path is None:
            return
        self._cancel_requested = False
        self.statusBar().showMessage("Retuš…")
        self.runner.run(
            self._retouch_job,
            on_finished=self._on_retouch_result,
            on_failed=self._on_failed,
            on_progress=self._on_progress,
        )

    def _retouch_job(self, progress=None) -> PipelineResult:
        return revectorize_mask(
            self.image_path,
            self.brush_mask,
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

    def _show_error(self, message: str) -> None:
        """Report an error through the status bar (no modal dialog in workers/tests)."""
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
