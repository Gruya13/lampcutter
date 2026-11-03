"""Profile editors (specification, 6.2, 6.3, 12.1)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from lampcutter.models import BaseProfile, MaterialProfile


def _spin(
    minimum: float,
    maximum: float,
    value: float,
    suffix: str = " mm",
    decimals: int = 2,
) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setValue(value)
    spin.setSuffix(suffix)
    spin.setSingleStep(0.1)
    return spin


def _buttons(dialog: QDialog) -> QDialogButtonBox:
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    return buttons


class MaterialEditorDialog(QDialog):
    """Edit one material profile (kerf, thickness, min feature, notes)."""

    def __init__(self, material: MaterialProfile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Uređivač materijala")
        self._material_id = material.id
        self.id_edit = QLineEdit(material.id)
        self.id_edit.setReadOnly(True)
        self.name_edit = QLineEdit(material.name)
        self.thickness_spin = _spin(0.5, 50.0, material.thickness_mm)
        self.kerf_spin = _spin(0.0, 2.0, material.kerf_mm, decimals=3)
        self.min_feature_spin = _spin(0.1, 20.0, material.min_feature_mm)
        self.notes_edit = QLineEdit(material.notes)
        form = QFormLayout()
        form.addRow("ID:", self.id_edit)
        form.addRow("Naziv:", self.name_edit)
        form.addRow("Debljina:", self.thickness_spin)
        form.addRow("Kerf:", self.kerf_spin)
        form.addRow("Najmanji detalj:", self.min_feature_spin)
        form.addRow("Napomene:", self.notes_edit)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(_buttons(self))

    def edited_material(self) -> MaterialProfile:
        return MaterialProfile(
            id=self._material_id,
            name=self.name_edit.text().strip() or self._material_id,
            thickness_mm=self.thickness_spin.value(),
            kerf_mm=self.kerf_spin.value(),
            min_feature_mm=self.min_feature_spin.value(),
            notes=self.notes_edit.text().strip(),
        )


class BaseEditorDialog(QDialog):
    """Edit one base profile (slot, tab and fit, specification 6.3 and 8.3)."""

    def __init__(self, base: BaseProfile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Uređivač postolja")
        self._base_id = base.id
        self.id_edit = QLineEdit(base.id)
        self.id_edit.setReadOnly(True)
        self.name_edit = QLineEdit(base.name)
        self.slot_length = _spin(1.0, 1000.0, base.slot_length_mm)
        self.slot_thickness = _spin(0.5, 100.0, base.slot_thickness_mm)
        self.slot_dimensions = QComboBox()
        self.slot_dimensions.addItem("Izmereno na bazi", "measured")
        self.slot_dimensions.addItem("Nominalno, laser reže", "nominal_laser_cut")
        index = self.slot_dimensions.findData(base.slot_dimensions)
        if index >= 0:
            self.slot_dimensions.setCurrentIndex(index)
        self.base_kerf = _spin(0.0, 3.0, base.base_kerf_mm, decimals=3)
        self.tab_width = _spin(1.0, 1000.0, base.tab_width_mm)
        self.tab_height = _spin(0.5, 100.0, base.tab_height_mm)
        self.tab_fit = _spin(-5.0, 5.0, base.tab_fit_mm)
        self.tab_offset = _spin(-200.0, 200.0, base.tab_offset_mm)
        self.corner_radius = _spin(0.0, 20.0, base.corner_radius_mm)
        form = QFormLayout()
        form.addRow("ID:", self.id_edit)
        form.addRow("Naziv:", self.name_edit)
        form.addRow("Dužina proreza:", self.slot_length)
        form.addRow("Debljina proreza:", self.slot_thickness)
        form.addRow("Vrsta dimenzija:", self.slot_dimensions)
        form.addRow("Kerf baze:", self.base_kerf)
        form.addRow("Širina jezička:", self.tab_width)
        form.addRow("Visina jezička:", self.tab_height)
        form.addRow("Zazor/fit:", self.tab_fit)
        form.addRow("Pomak:", self.tab_offset)
        form.addRow("Radijus ugla:", self.corner_radius)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(_buttons(self))

    def edited_base(self) -> BaseProfile:
        return BaseProfile(
            id=self._base_id,
            name=self.name_edit.text().strip() or self._base_id,
            slot_length_mm=self.slot_length.value(),
            slot_thickness_mm=self.slot_thickness.value(),
            slot_dimensions=str(self.slot_dimensions.currentData()),
            base_kerf_mm=self.base_kerf.value(),
            tab_width_mm=self.tab_width.value(),
            tab_height_mm=self.tab_height.value(),
            tab_fit_mm=self.tab_fit.value(),
            tab_offset_mm=self.tab_offset.value(),
            corner_radius_mm=self.corner_radius.value(),
        )
