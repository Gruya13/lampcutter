"""Canvas: image, mask, contour and prompt interaction (specification, 12.1).

Scene coordinates are image pixels; the view uses `setTransform` with
`ViewTransform` so that zoom/pan match the Qt-free maths in `ui/tools.py`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)

from lampcutter.core import io_utils
from lampcutter.ui.tools import PolygonTool, PromptBuilder, ViewTransform

PROMPT_COLORS = {1: QColor(40, 200, 60, 220), 0: QColor(220, 50, 50, 220)}
CONTOUR_COLOR = QColor(255, 0, 0, 230)
SLOT_COLOR = QColor(0, 160, 220, 220)
DECOR_COLOR = QColor(0, 80, 255, 220)
POLYGON_COLOR = QColor(255, 170, 0, 230)


class Canvas(QGraphicsView):
    """Graphics view over the working image with prompt and polygon tools."""

    prompt_point_added = Signal(int, float, float)  # label, image x, image y
    box_selected = Signal(float, float, float, float)  # image px box
    polygon_finished = Signal(list)  # list of (x, y) image px
    prompt_cleared = Signal()
    image_loaded = Signal(str, int, int)  # path, width, height

    MODE_PROMPT = "prompt"
    MODE_POLYGON = "polygon"
    DRAG_THRESHOLD = 4.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QColor(35, 35, 40))
        self.view_transform = ViewTransform()
        self.prompt_builder = PromptBuilder()
        self.polygon_tool = PolygonTool()
        self.mode = self.MODE_PROMPT
        self._image_array: np.ndarray | None = None
        self._image_item: QGraphicsPixmapItem | None = None
        self._mask_item: QGraphicsPixmapItem | None = None
        self._contour_item: QGraphicsPathItem | None = None
        self._slot_items: list[QGraphicsPathItem] = []
        self._decor_items: list[QGraphicsPathItem] = []
        self._prompt_items: list[QGraphicsItem] = []
        self._box_item: QGraphicsRectItem | None = None
        self._polygon_item: QGraphicsPathItem | None = None
        self._press_pos: QPointF | None = None
        self._press_image: tuple[float, float] | None = None
        self._dragging_box = False
        self._panning = False
        self._last_pan_pos: QPointF | None = None

    # ------------------------------------------------------------------ data
    @property
    def image_array(self) -> np.ndarray | None:
        return self._image_array

    def image_size(self) -> tuple[int, int]:
        if self._image_array is None:
            return (0, 0)
        return (int(self._image_array.shape[1]), int(self._image_array.shape[0]))

    def set_image(self, path: str | Path) -> tuple[int, int]:
        """Load an image (EXIF applied) and fit it into the view."""
        image = io_utils.load_image(Path(path), min_resolution_px=1)
        array = np.asarray(image.convert("RGB"), dtype=np.uint8)
        self._image_array = array
        height, width = array.shape[:2]
        qimage = QImage(array.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qimage)
        if self._image_item is None:
            self._image_item = self._scene.addPixmap(pixmap)
            self._image_item.setZValue(0)
        else:
            self._image_item.setPixmap(pixmap)
        self._scene.setSceneRect(QRectF(0, 0, width, height))
        self.fit_view()
        self.image_loaded.emit(str(path), width, height)
        return (width, height)

    def set_mask(self, mask: np.ndarray | None, alpha: int = 110) -> None:
        """Overlay the segmentation mask (semi-transparent)."""
        if self._mask_item is not None:
            self._scene.removeItem(self._mask_item)
            self._mask_item = None
        if mask is None or not mask.any():
            return
        height, width = mask.shape
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[mask] = (255, 230, 0, alpha)
        qimage = QImage(rgba.data, width, height, 4 * width, QImage.Format.Format_RGBA8888).copy()
        self._mask_item = self._scene.addPixmap(QPixmap.fromImage(qimage))
        self._mask_item.setZValue(1)

    def set_overlay_geometry(
        self,
        polygons_mm: list[object],
        mm_per_px: float,
        color: QColor = CONTOUR_COLOR,
        width: float = 2.0,
    ) -> None:
        """Draw polygons given in millimetres onto the image (scene = pixels)."""
        for item in [self._contour_item, *self._slot_items, *self._decor_items]:
            if item is not None:
                self._scene.removeItem(item)
        self._contour_item = None
        self._slot_items = []
        self._decor_items = []
        if not polygons_mm or mm_per_px <= 0:
            return
        path = self._polygons_to_path(polygons_mm, mm_per_px)
        item = QGraphicsPathItem(path)
        item.setPen(QPen(color, width))
        item.setZValue(3)
        self._scene.addItem(item)
        self._contour_item = item

    def set_slots(self, polygons_mm: list[object], mm_per_px: float) -> None:
        for item in self._slot_items:
            self._scene.removeItem(item)
        self._slot_items = []
        if mm_per_px <= 0:
            return
        for polygon in polygons_mm:
            item = QGraphicsPathItem(self._polygons_to_path([polygon], mm_per_px))
            item.setPen(QPen(SLOT_COLOR, 1.5, Qt.PenStyle.DashLine))
            item.setZValue(4)
            self._scene.addItem(item)
            self._slot_items.append(item)

    def set_decor(self, polygons_mm: list[object], mm_per_px: float) -> None:
        for item in self._decor_items:
            self._scene.removeItem(item)
        self._decor_items = []
        if mm_per_px <= 0:
            return
        for polygon in polygons_mm:
            item = QGraphicsPathItem(self._polygons_to_path([polygon], mm_per_px))
            item.setPen(QPen(DECOR_COLOR, 1.5, Qt.PenStyle.DotLine))
            item.setZValue(5)
            self._scene.addItem(item)
            self._decor_items.append(item)

    @staticmethod
    def _polygons_to_path(polygons: list[object], mm_per_px: float) -> QPainterPath:
        path = QPainterPath()
        for polygon in polygons:
            exterior = getattr(polygon, "exterior", None)
            if exterior is None:
                continue
            coords = list(exterior.coords)
            if len(coords) < 3:
                continue
            first = coords[0]
            path.moveTo(first[0] / mm_per_px, first[1] / mm_per_px)
            for point in coords[1:]:
                path.lineTo(point[0] / mm_per_px, point[1] / mm_per_px)
            path.closeSubpath()
        return path

    # --------------------------------------------------------------- view ops
    def fit_view(self) -> None:
        width, height = self.image_size()
        if width == 0 or height == 0:
            return
        self.view_transform = ViewTransform().fit(
            (width, height), (max(1, self.viewport().width()), max(1, self.viewport().height()))
        )
        self._apply_transform()

    def zoom(self, factor: float, view_point: QPointF | None = None) -> None:
        center = (
            view_point
            if view_point is not None
            else QPointF(self.viewport().width() / 2.0, self.viewport().height() / 2.0)
        )
        self.view_transform = self.view_transform.zoom_at((center.x(), center.y()), factor)
        self._apply_transform()

    def _apply_transform(self) -> None:
        transform = self.view_transform
        self.setTransform(
            QTransform(transform.zoom, 0.0, 0.0, transform.zoom, transform.pan_x, transform.pan_y)
        )

    # ------------------------------------------------------------ interaction
    def set_mode(self, mode: str) -> None:
        if mode not in (self.MODE_PROMPT, self.MODE_POLYGON):
            raise ValueError(f"nepoznat režim platna {mode!r}")
        self.mode = mode

    def add_prompt_point(self, label: int, image_point: tuple[float, float]) -> None:
        """Add a prompt point and draw it (used by clicks and by tests)."""
        if label not in (0, 1):
            raise ValueError("label mora biti 0 ili 1")
        if self.mode == self.MODE_POLYGON:
            raise ValueError("prompt tačke nisu dostupne u režimu poligona")
        if label == 1:
            self.prompt_builder.add_positive(image_point)
        else:
            self.prompt_builder.add_negative(image_point)
        radius = max(3.0, 6.0 / max(self.view_transform.zoom, 1e-6))
        item = QGraphicsEllipseItem(
            image_point[0] - radius / 2, image_point[1] - radius / 2, radius, radius
        )
        item.setBrush(PROMPT_COLORS[label])
        item.setPen(QPen(QColor(255, 255, 255, 200), 1.0))
        item.setZValue(6)
        self._scene.addItem(item)
        self._prompt_items.append(item)
        self.prompt_point_added.emit(label, image_point[0], image_point[1])

    def select_box(self, image_box: tuple[float, float, float, float]) -> None:
        """Record and draw a prompt box (image pixels)."""
        self.prompt_builder.set_box(image_box)
        if self._box_item is not None:
            self._scene.removeItem(self._box_item)
        x0, y0, x1, y1 = self.prompt_builder.box or image_box
        self._box_item = QGraphicsRectItem(QRectF(QPointF(x0, y0), QPointF(x1, y1)))
        self._box_item.setPen(QPen(QColor(70, 200, 255, 230), 1.5, Qt.PenStyle.DashLine))
        self._box_item.setZValue(6)
        self._scene.addItem(self._box_item)
        self.box_selected.emit(x0, y0, x1, y1)

    def add_polygon_vertex(self, image_point: tuple[float, float]) -> None:
        if self.mode != self.MODE_POLYGON:
            raise ValueError("poligon alat nije aktivan")
        self.polygon_tool.add_point(image_point)
        self._redraw_polygon()

    def finish_polygon(self) -> list[tuple[int, int]]:
        points = self.polygon_tool.finish()
        item = self._polygon_item
        if item is not None:
            item.setPen(QPen(POLYGON_COLOR, 2.0))
        self.polygon_finished.emit(points)
        return points

    def _redraw_polygon(self) -> None:
        if self._polygon_item is not None:
            self._scene.removeItem(self._polygon_item)
            self._polygon_item = None
        points = self.polygon_tool.points
        if not points:
            return
        path = QPainterPath()
        path.moveTo(points[0][0], points[0][1])
        for point in points[1:]:
            path.lineTo(point[0], point[1])
        item = QGraphicsPathItem(path)
        item.setPen(QPen(POLYGON_COLOR, 2.0, Qt.PenStyle.DashLine))
        item.setZValue(6)
        self._scene.addItem(item)
        self._polygon_item = item

    def undo_last(self) -> bool:
        """Remove the last prompt point, box or polygon vertex (specification, 12.1)."""
        if self.mode == self.MODE_POLYGON:
            if self.polygon_tool.undo():
                self._redraw_polygon()
                return True
            return False
        if self._box_item is not None:
            self._scene.removeItem(self._box_item)
            self._box_item = None
            self.prompt_builder.undo()
            return True
        if self._prompt_items:
            item = self._prompt_items.pop()
            self._scene.removeItem(item)
        return self.prompt_builder.undo()

    def load_prompt(self, prompt) -> None:
        """Replace the current prompt with a saved one (project open)."""
        self.clear_prompt()
        for point, label in zip(prompt.points, prompt.labels, strict=False):
            self.add_prompt_point(int(label), (float(point[0]), float(point[1])))
        if prompt.box is not None:
            self.select_box(tuple(float(value) for value in prompt.box))

    def load_polygon(self, points: list[tuple[int, int]]) -> None:
        """Replace the manual polygon with a saved one (project open)."""
        self.polygon_tool.reset()
        for point in points:
            self.add_polygon_vertex((float(point[0]), float(point[1])))
        self._redraw_polygon()

    def clear_prompt(self) -> None:
        """Remove every prompt marker and reset the builder."""
        for item in self._prompt_items:
            self._scene.removeItem(item)
        self._prompt_items = []
        if self._box_item is not None:
            self._scene.removeItem(self._box_item)
            self._box_item = None
        self.prompt_builder.reset()
        self.prompt_cleared.emit()

    # ---------------------------------------------------------------- events
    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.2 ** (delta / 120.0)
        self.zoom(factor, event.position())
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._last_pan_pos = event.position()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton and self.mode == self.MODE_POLYGON:
            if len(self.polygon_tool.points) >= 3:
                self.finish_polygon()
            event.accept()
            return
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            image_point = self.view_transform.view_to_image(
                (event.position().x(), event.position().y())
            )
            self._press_pos = event.position()
            self._press_image = image_point
            self._dragging_box = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning and self._last_pan_pos is not None:
            delta = event.position() - self._last_pan_pos
            self._last_pan_pos = event.position()
            self.view_transform = ViewTransform(
                zoom=self.view_transform.zoom,
                pan_x=self.view_transform.pan_x + delta.x(),
                pan_y=self.view_transform.pan_y + delta.y(),
            )
            self._apply_transform()
            event.accept()
            return
        if (
            self._press_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and self.mode == self.MODE_PROMPT
        ):
            distance = (event.position() - self._press_pos).manhattanLength()
            if distance > self.DRAG_THRESHOLD:
                self._dragging_box = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning and event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self._last_pan_pos = None
            event.accept()
            return
        press_image = self._press_image
        press_pos = self._press_pos
        dragging = self._dragging_box
        self._press_image = None
        self._press_pos = None
        self._dragging_box = False
        if press_image is not None and press_pos is not None:
            image_point = self.view_transform.view_to_image(
                (event.position().x(), event.position().y())
            )
            if self.mode == self.MODE_POLYGON and event.button() == Qt.MouseButton.LeftButton:
                self.add_polygon_vertex(image_point)
                event.accept()
                return
            if self.mode == self.MODE_PROMPT:
                label = 1 if event.button() == Qt.MouseButton.LeftButton else 0
                if dragging and event.button() == Qt.MouseButton.LeftButton:
                    self.select_box(
                        (
                            min(press_image[0], image_point[0]),
                            min(press_image[1], image_point[1]),
                            max(press_image[0], image_point[0]),
                            max(press_image[1], image_point[1]),
                        )
                    )
                else:
                    self.add_prompt_point(label, image_point)
                event.accept()
                return
        super().mouseReleaseEvent(event)
