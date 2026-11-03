"""Qt-free interaction logic for the GUI (specification, 12.1).

Everything here is plain Python: the view transform, the prompt builder, the
manual polygon tool and the request-generation counter. Keeping it Qt-free lets
the interaction rules be tested headlessly and deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lampcutter.models import Prompt

Point = tuple[float, float]


@dataclass
class ViewTransform:
    """Mapping between image pixels and view pixels (zoom + pan, both axes equal)."""

    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0

    def __post_init__(self) -> None:
        if self.zoom <= 0:
            raise ValueError("zoom must be positive")

    def image_to_view(self, point: Point) -> Point:
        return (point[0] * self.zoom + self.pan_x, point[1] * self.zoom + self.pan_y)

    def view_to_image(self, point: Point) -> Point:
        return ((point[0] - self.pan_x) / self.zoom, (point[1] - self.pan_y) / self.zoom)

    def zoom_at(self, view_point: Point, factor: float) -> ViewTransform:
        """Zoom around a fixed point so that the pixel under the cursor stays put."""
        if factor <= 0:
            raise ValueError("factor must be positive")
        image_point = self.view_to_image(view_point)
        new_zoom = max(1e-3, min(200.0, self.zoom * factor))
        return ViewTransform(
            zoom=new_zoom,
            pan_x=view_point[0] - image_point[0] * new_zoom,
            pan_y=view_point[1] - image_point[1] * new_zoom,
        )

    def fit(
        self,
        image_size: tuple[int, int],
        view_size: tuple[int, int],
        margin: float = 0.02,
    ) -> ViewTransform:
        """Transform that fits the whole image inside the view with a small margin."""
        image_width, image_height = image_size
        view_width, view_height = view_size
        if image_width <= 0 or image_height <= 0 or view_width <= 0 or view_height <= 0:
            raise ValueError("veličine slike i platna moraju biti pozitivne")
        usable_w = view_width * (1.0 - 2 * margin)
        usable_h = view_height * (1.0 - 2 * margin)
        zoom = min(usable_w / image_width, usable_h / image_height)
        pan_x = (view_width - image_width * zoom) / 2.0
        pan_y = (view_height - image_height * zoom) / 2.0
        return ViewTransform(zoom=zoom, pan_x=pan_x, pan_y=pan_y)


@dataclass
class PromptBuilder:
    """Collects positive/negative points and one box, with undo (specification, 12.1)."""

    positive: list[Point] = field(default_factory=list)
    negative: list[Point] = field(default_factory=list)
    box: tuple[float, float, float, float] | None = None

    def add_positive(self, point: Point) -> None:
        self.positive.append(point)

    def add_negative(self, point: Point) -> None:
        self.negative.append(point)

    def set_box(self, box: tuple[float, float, float, float]) -> None:
        x0, y0, x1, y1 = box
        if x1 == x0 or y1 == y0:
            raise ValueError("okvir mora imati pozitivnu širinu i visinu")
        self.box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    def undo(self) -> bool:
        """Remove the last action (point or box). Returns False when nothing to undo."""
        if self.box is not None:
            self.box = None
            return True
        if self.negative:
            self.negative.pop()
            return True
        if self.positive:
            self.positive.pop()
            return True
        return False

    def reset(self) -> None:
        self.positive.clear()
        self.negative.clear()
        self.box = None

    @property
    def is_empty(self) -> bool:
        return not self.positive and not self.negative and self.box is None

    def to_prompt(self) -> Prompt:
        """Build the immutable `Prompt` used by the pipeline."""
        points = [(round(x), round(y)) for x, y in self.positive]
        points += [(round(x), round(y)) for x, y in self.negative]
        labels = [1] * len(self.positive) + [0] * len(self.negative)
        box = None
        if self.box is not None:
            box = tuple(round(value) for value in self.box)  # type: ignore[assignment]
        return Prompt(points=tuple(points), labels=tuple(labels), box=box)


@dataclass
class PolygonTool:
    """Manual polygon tool: click vertices, finish with at least 3 (specification, 12.1)."""

    points: list[Point] = field(default_factory=list)
    closed: bool = False

    def add_point(self, point: Point) -> None:
        if self.closed:
            raise ValueError("poligon je već zatvoren")
        self.points.append((float(point[0]), float(point[1])))

    def undo(self) -> bool:
        if not self.points:
            return False
        self.points.pop()
        self.closed = False
        return True

    def reset(self) -> None:
        self.points.clear()
        self.closed = False

    def finish(self) -> list[Point]:
        """Close the polygon; needs at least three vertices."""
        if len(self.points) < 3:
            raise ValueError("poligon mora imati bar 3 tačke")
        self.closed = True
        return [(round(x), round(y)) for x, y in self.points]


class GenerationCounter:
    """Monotonic request counter used to drop stale async results (specification, 12.2)."""

    def __init__(self) -> None:
        self._current = 0

    def next(self) -> int:
        self._current += 1
        return self._current

    @property
    def current(self) -> int:
        return self._current

    def is_current(self, generation: int) -> bool:
        return generation == self._current
