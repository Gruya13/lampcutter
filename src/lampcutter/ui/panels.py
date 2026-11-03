"""Side panels for the main window (specification, 12.1)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from lampcutter.models import BaseProfile, DecorElement, MaterialProfile, PhotoSlot

COMMON_SIZES_MM = {"S": 150.0, "M": 200.0, "L": 250.0}


class SizePanel(QGroupBox):
    """Reference side, value, unit and computed dimensions (specification, 12.1)."""

    size_changed = Signal(str, float)  # reference, value in mm

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Veličina", parent)
        self.reference_combo = QComboBox()
        self.reference_combo.addItem("Visina", "height")
        self.reference_combo.addItem("Širina", "width")
        self.unit_combo = QComboBox()
        self.unit_combo.addItem("mm", 1.0)
        self.unit_combo.addItem("cm", 10.0)
        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(1.0, 20000.0)
        self.value_spin.setDecimals(1)
        self.value_spin.setValue(200.0)
        self.value_spin.setSuffix(" mm")
        self.computed_label = QLabel("—")
        self.computed_label.setWordWrap(True)

        form = QFormLayout(self)
        form.addRow("Referentna strana:", self.reference_combo)
        form.addRow("Vrednost:", self.value_spin)
        form.addRow("Jedinica:", self.unit_combo)
        form.addRow("Izračunato:", self.computed_label)

        quick = QHBoxLayout()
        for label, value in COMMON_SIZES_MM.items():
            button = QPushButton(label)
            button.setToolTip(f"{value:.0f} mm")
            button.clicked.connect(lambda _checked=False, value=value: self.set_value_mm(value))
            quick.addWidget(button)
        container = QWidget()
        container.setLayout(quick)
        form.addRow("Česte veličine:", container)

        self.value_spin.valueChanged.connect(self._emit_change)
        self.reference_combo.currentIndexChanged.connect(self._emit_change)
        self.unit_combo.currentIndexChanged.connect(self._unit_changed)

    def reference(self) -> str:
        return str(self.reference_combo.currentData())

    def unit_factor(self) -> float:
        return float(self.unit_combo.currentData())

    def value_mm(self) -> float:
        return self.value_spin.value() * self.unit_factor()

    def set_reference(self, reference: str) -> None:
        index = self.reference_combo.findData(reference)
        if index >= 0:
            self.reference_combo.setCurrentIndex(index)

    def set_value_mm(self, value_mm: float) -> None:
        self.value_spin.setValue(value_mm / self.unit_factor())
        self._emit_change()

    def set_computed(self, width_mm: float, height_mm: float, total_height_mm: float) -> None:
        self.computed_label.setText(
            f"{width_mm:.2f} x {height_mm:.2f} mm; sa jezičkom {total_height_mm:.2f} mm"
        )

    def _unit_changed(self) -> None:
        factor = self.unit_factor()
        previous = self._previous_factor()
        self.value_spin.blockSignals(True)
        self.value_spin.setValue(self.value_spin.value() * (previous / factor))
        self.value_spin.blockSignals(False)
        self.value_spin.setSuffix(" mm" if factor == 1.0 else " cm")

    def _previous_factor(self) -> float:
        return 1.0 if self.value_spin.suffix() == " mm" else 10.0

    def _emit_change(self) -> None:
        self.size_changed.emit(self.reference(), self.value_mm())


class MaterialPanel(QGroupBox):
    """Material selection with a profile editor (specification, 6.2, 12.1)."""

    material_changed = Signal(str)
    edit_requested = Signal()

    def __init__(
        self,
        materials: list[MaterialProfile] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Materijal", parent)
        self.combo = QComboBox()
        layout = QVBoxLayout(self)
        layout.addWidget(self.combo)
        row = QHBoxLayout()
        self.edit_button = QPushButton("Uredi…")
        self.edit_button.clicked.connect(self.edit_requested.emit)
        row.addWidget(self.edit_button)
        container = QWidget()
        container.setLayout(row)
        layout.addWidget(container)
        self.combo.currentIndexChanged.connect(
            lambda _index: self.material_changed.emit(self.current_material_id())
        )
        self.set_materials(materials or [])

    def set_materials(self, materials: list[MaterialProfile]) -> None:
        current = self.current_material_id()
        self.combo.blockSignals(True)
        self.combo.clear()
        for material in materials:
            self.combo.addItem(material.name, material.id)
        index = self.combo.findData(current)
        if index >= 0:
            self.combo.setCurrentIndex(index)
        self.combo.blockSignals(False)

    def select_material(self, material_id: str) -> None:
        index = self.combo.findData(material_id)
        if index >= 0:
            self.combo.setCurrentIndex(index)

    def current_material_id(self) -> str:
        return str(self.combo.currentData() or "")


class BasePanel(QGroupBox):
    """Base profile fields with live clearance preview (specification, 12.1, 8.3)."""

    base_changed = Signal(dict)
    edit_requested = Signal()

    def __init__(
        self,
        bases: list[BaseProfile] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Postolje", parent)
        self.combo = QComboBox()
        self.slot_length = _spin(1.0, 1000.0, 80.0, " mm")
        self.slot_thickness = _spin(0.5, 100.0, 3.4, " mm")
        self.tab_width = _spin(1.0, 1000.0, 78.0, " mm")
        self.tab_height = _spin(0.5, 100.0, 8.0, " mm")
        self.tab_fit = _spin(-5.0, 5.0, 0.0, " mm")
        self.tab_offset = _spin(-200.0, 200.0, 0.0, " mm")
        self.corner_radius = _spin(0.0, 20.0, 0.5, " mm")

        self.edit_button = QPushButton("Uredi…")
        self.edit_button.clicked.connect(self.edit_requested.emit)
        profile_row = QWidget()
        profile_row_layout = QHBoxLayout(profile_row)
        profile_row_layout.setContentsMargins(0, 0, 0, 0)
        profile_row_layout.addWidget(self.combo, 1)
        profile_row_layout.addWidget(self.edit_button)

        form = QFormLayout(self)
        form.addRow("Profil:", profile_row)
        form.addRow("Dužina proreza:", self.slot_length)
        form.addRow("Debljina proreza:", self.slot_thickness)
        form.addRow("Širina jezička:", self.tab_width)
        form.addRow("Visina jezička:", self.tab_height)
        form.addRow("Zazor/fit jezička:", self.tab_fit)
        form.addRow("Pomak jezička:", self.tab_offset)
        form.addRow("Radijus ugla:", self.corner_radius)
        self.clearance_label = QLabel("—")
        form.addRow("Zazor u ravni:", self.clearance_label)

        self.combo.currentIndexChanged.connect(self._load_profile)
        for spin in (
            self.slot_length,
            self.slot_thickness,
            self.tab_width,
            self.tab_height,
            self.tab_fit,
            self.tab_offset,
            self.corner_radius,
        ):
            spin.valueChanged.connect(lambda _value: self._emit_change())
        self._bases: list[BaseProfile] = []
        self.set_bases(bases or [])

    def set_bases(self, bases: list[BaseProfile]) -> None:
        self._bases = list(bases)
        self.combo.blockSignals(True)
        self.combo.clear()
        for base in bases:
            self.combo.addItem(base.name, base.id)
        self.combo.blockSignals(False)
        self._load_profile()

    def current_base_id(self) -> str:
        return str(self.combo.currentData() or "")

    def select_base(self, base_id: str | None) -> None:
        index = self.combo.findData(base_id) if base_id is not None else -1
        if index >= 0:
            self.combo.setCurrentIndex(index)

    def set_values(self, values: dict) -> None:
        """Apply values from a saved project without emitting loops."""
        self.blockSignals(True)
        for key, widget in (
            ("slot_length_mm", self.slot_length),
            ("slot_thickness_mm", self.slot_thickness),
            ("tab_width_mm", self.tab_width),
            ("tab_height_mm", self.tab_height),
            ("tab_fit_mm", self.tab_fit),
            ("tab_offset_mm", self.tab_offset),
            ("corner_radius_mm", self.corner_radius),
        ):
            if key in values:
                widget.setValue(float(values[key]))
        self.blockSignals(False)
        self._emit_change()

    def values(self) -> dict:
        return {
            "slot_length_mm": self.slot_length.value(),
            "slot_thickness_mm": self.slot_thickness.value(),
            "tab_width_mm": self.tab_width.value(),
            "tab_height_mm": self.tab_height.value(),
            "tab_fit_mm": self.tab_fit.value(),
            "tab_offset_mm": self.tab_offset.value(),
            "corner_radius_mm": self.corner_radius.value(),
        }

    def set_clearance(self, planar_mm: float, thickness_mm: float) -> None:
        self.clearance_label.setText(f"{planar_mm:+.2f} mm (po debljini {thickness_mm:+.2f} mm)")

    def _load_profile(self) -> None:
        index = self.combo.currentIndex()
        if not (0 <= index < len(self._bases)):
            return
        base = self._bases[index]
        self.blockSignals(True)
        self.slot_length.setValue(base.slot_length_mm)
        self.slot_thickness.setValue(base.slot_thickness_mm)
        self.tab_width.setValue(base.tab_width_mm)
        self.tab_height.setValue(base.tab_height_mm)
        self.tab_fit.setValue(base.tab_fit_mm)
        self.tab_offset.setValue(base.tab_offset_mm)
        self.corner_radius.setValue(base.corner_radius_mm)
        self.blockSignals(False)
        self._emit_change()

    def _emit_change(self) -> None:
        self.base_changed.emit(self.values())


class ContourPanel(QGroupBox):
    """Contour settings (specification, 12.1)."""

    contour_changed = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Kontura", parent)
        self.input_kind = QComboBox()
        self.input_kind.addItem("Mockup", "mockup")
        self.input_kind.addItem("Fotografija", "photo")
        self.edge_inset = _spin(0.0, 5.0, 0.5, " mm", decimals=2)
        self.kerf_mode = QComboBox()
        self.kerf_mode.addItem("Aplikacija (offset u aplikaciji)", "app")
        self.kerf_mode.addItem("LightBurn (offset u LightBurn-u)", "lightburn")
        self.smoothness = _spin(0.0, 2.0, 0.03, " mm", decimals=3)
        form = QFormLayout(self)
        form.addRow("Vrsta ulaza:", self.input_kind)
        form.addRow("Uvlačenje ivice:", self.edge_inset)
        form.addRow("Kerf kompenzacija:", self.kerf_mode)
        form.addRow("Glatkoća (simplify):", self.smoothness)
        for widget in (self.edge_inset, self.smoothness):
            widget.valueChanged.connect(lambda _value: self._emit_change())
        for combo in (self.input_kind, self.kerf_mode):
            combo.currentIndexChanged.connect(lambda _index: self._emit_change())

    def set_values(self, values: dict) -> None:
        index = self.input_kind.findData(values.get("input_kind"))
        if index >= 0:
            self.input_kind.setCurrentIndex(index)
        if "edge_inset_mm" in values:
            self.edge_inset.setValue(float(values["edge_inset_mm"]))
        index = self.kerf_mode.findData(values.get("kerf_mode"))
        if index >= 0:
            self.kerf_mode.setCurrentIndex(index)
        if "simplify_tol_mm" in values:
            self.smoothness.setValue(float(values["simplify_tol_mm"]))

    def values(self) -> dict:
        return {
            "input_kind": str(self.input_kind.currentData()),
            "edge_inset_mm": self.edge_inset.value(),
            "kerf_mode": str(self.kerf_mode.currentData()),
            "simplify_tol_mm": self.smoothness.value(),
        }

    def _emit_change(self) -> None:
        self.contour_changed.emit(self.values())


class ElementsPanel(QGroupBox):
    """Slot and decor list with per-element mode (specification, 12.1 and 9.3)."""

    mode_changed = Signal(str, str)  # element id, mode
    element_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Elementi", parent)
        self.list = QListWidget()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Gravura", "engrave")
        self.mode_combo.addItem("Štampa", "print")
        self.mode_combo.addItem("Ništa", "none")
        self.mode_combo.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addWidget(QLabel("Režim izabranog elementa:"))
        layout.addWidget(self.mode_combo)
        self.list.currentItemChanged.connect(self._on_selection)
        self.mode_combo.currentIndexChanged.connect(self._on_mode)

    def set_elements(self, slots: list[PhotoSlot], decor: list[DecorElement]) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for slot in slots:
            item = QListWidgetItem(f"Slot: {slot.id} ({slot.source})")
            item.setData(Qt.ItemDataRole.UserRole, ("slot", slot.id))
            self.list.addItem(item)
        for element in decor:
            item = QListWidgetItem(f"Dekor: {element.id} ({element.mode})")
            item.setData(Qt.ItemDataRole.UserRole, ("decor", element.id))
            self.list.addItem(item)
        self.list.blockSignals(False)

    def current_element(self) -> tuple[str, str] | None:
        item = self.list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return (str(data[0]), str(data[1])) if data else None

    def _on_selection(self, _current, _previous) -> None:
        element = self.current_element()
        self.mode_combo.setEnabled(element is not None and element[0] == "decor")
        if element is not None:
            self.element_selected.emit(element[1])

    def _on_mode(self) -> None:
        element = self.current_element()
        if element is None or element[0] != "decor":
            return
        self.mode_changed.emit(element[1], str(self.mode_combo.currentData()))


class BrushPanel(QGroupBox):
    """Manual mask retouch brush (v1.1, specification 12.1)."""

    brush_changed = Signal(int, bool)  # radius_px, add
    undo_requested = Signal()

    def __init__(self, radius_px: int = 25, parent: QWidget | None = None) -> None:
        super().__init__("Četkica (retuš maske)", parent)
        self.radius_spin = QSpinBox()
        self.radius_spin.setRange(1, 500)
        self.radius_spin.setValue(int(radius_px))
        self.radius_spin.setSuffix(" px")
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Dodaj u masku", True)
        self.mode_combo.addItem("Ukloni iz maske", False)
        self.info_label = QLabel("Levi taster = dodaj, desni = ukloni.")
        self.info_label.setWordWrap(True)
        self.undo_button = QPushButton("Poništi potez")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Veličina četkice:"))
        layout.addWidget(self.radius_spin)
        layout.addWidget(self.mode_combo)
        layout.addWidget(self.info_label)
        layout.addWidget(self.undo_button)
        self.radius_spin.valueChanged.connect(lambda _value: self._emit_change())
        self.mode_combo.currentIndexChanged.connect(lambda _index: self._emit_change())
        self.undo_button.clicked.connect(self.undo_requested.emit)

    def radius_px(self) -> int:
        return int(self.radius_spin.value())

    def add_mode(self) -> bool:
        return bool(self.mode_combo.currentData())

    def set_from_config(self, config) -> None:
        self.radius_spin.setValue(int(config.brush_radius_px))

    def _emit_change(self) -> None:
        self.brush_changed.emit(self.radius_px(), self.add_mode())


def _spin(
    minimum: float,
    maximum: float,
    value: float,
    suffix: str,
    decimals: int = 1,
) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setValue(value)
    spin.setSuffix(suffix)
    spin.setSingleStep(0.1)
    return spin
