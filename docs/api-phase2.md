# API ugovor — Faza 2 (GUI kostur)

Dopuna ugovora iz 0a/0b/1. Faza 2 pokriva GUI kostur (spec 12, 16): platno,
nitovi, interaktivni prompt, poligon alat, lista slotova/elemenata.

**Okruženje za testove:** GUI testovi rade **offscreen**:

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # PRE importa PySide6
pytest.importorskip("PySide6")
```

QApplication se pravi jednom (session fixture); asinhroni testovi koriste
`pytest-qt` (`qtbot.waitUntil`) ili `QApplication.processEvents()` u petlji.
Ne testirati `run_gui` (ulazi u event loop).

## `lampcutter.ui.tools` — Qt-free logika

```python
@dataclass
class ViewTransform:
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    def image_to_view(self, point) -> tuple[float, float]: ...
    def view_to_image(self, point) -> tuple[float, float]: ...
    def zoom_at(self, view_point, factor) -> ViewTransform: ...
    def fit(self, image_size, view_size, margin=0.02) -> ViewTransform: ...

@dataclass
class PromptBuilder:
    positive: list / negative: list / box: tuple | None
    def add_positive(point) / add_negative(point) / set_box(box) / undo() -> bool
    def reset() / is_empty -> bool / to_prompt() -> Prompt

@dataclass
class PolygonTool:
    points: list / closed: bool
    def add_point(point) / undo() -> bool / reset() / finish() -> list[tuple[int, int]]

class GenerationCounter:
    def next() -> int / current -> int / is_current(generation) -> bool
```

- `ViewTransform`: `image_to_view` i `view_to_image` su inverzni (tolerancija
  1e-9); `zoom_at` menja `zoom` tako da **tačka pod kursorom ostane na istom
  pikselu** (krug: image→view→zoom→view→image ≈ ista tačka); `fit` centrira
  sliku u platnu (leva i desna margina jednake, unutar 1e-6); `zoom <= 0` i
  negativan `factor` → `ValueError`.
- `PromptBuilder`: `to_prompt()` daje redom pozitivne pa negativne tačke sa
  labelama `1`/`0`, box normalizovan; `undo()` uklanja **poslednju radnju**
  (prvo box, pa poslednju tačku) i vraća False ako nema šta; `reset`.
- `PolygonTool`: `finish()` sa < 3 tačke → `ValueError`; posle `finish()`
  `add_point` → `ValueError`; `undo()` vraća True/False.
- `GenerationCounter`: `is_current` je True samo za poslednju generaciju.

## `lampcutter.ui.workers` — nitovi (spec 12.2)

```python
class TaskRunner(QObject):
    def run(self, function, *args, on_finished=None, on_failed=None,
            on_progress=None, **kwargs) -> int
    last_result / last_error
    def cancel(self) -> None
    def wait(self, timeout_ms=5000) -> bool

class Debouncer(QObject):
    def __init__(self, interval_ms=150, parent=None)
    def schedule(self, callback) -> None
    def cancel(self) -> None
```

- `run` vraća generaciju; `on_finished(result)` se poziva **samo za najnoviju**
  generaciju (stariji rezultat se odbacuje), `on_failed(message)` za grešku
  (poruka sadrži tip i opis), `on_progress(stage, fraction)` se prosleđuje.
- Test stale: prvo pokreni spor zadatak koji vraća "spor" (npr. `time.sleep(0.3)`),
  pa brz koji vraća "brz"; posle obrade samo "brz" sme da stigne u callback.
- `cancel()` invalidira sve tekuće zadatke (njihovi callbackovi se ne pozivaju).
- `Debouncer(60)`: tri `schedule` poziva u burstu → izvršava se samo poslednji.
- `wait()` blokira do kraja (za teardown).

## `lampcutter.ui.canvas` — platno

```python
class Canvas(QGraphicsView):
    prompt_point_added = Signal(int, float, float)   # label, image x, image y
    box_selected = Signal(float, float, float, float)
    polygon_finished = Signal(list)
    prompt_cleared = Signal()
    image_loaded = Signal(str, int, int)
    MODE_PROMPT = "prompt"; MODE_POLYGON = "polygon"

    def set_image(path) -> tuple[int, int]      # EXIF, scene = pikseli slike
    def image_size() -> tuple[int, int]
    def set_mask(mask | None) -> None
    def set_overlay_geometry(polygons_mm, mm_per_px, ...) -> None
    def set_slots(polygons_mm, mm_per_px) / set_decor(polygons_mm, mm_per_px)
    def set_mode(mode)                          # nepoznat → ValueError
    def add_prompt_point(label, image_point)    # label 0/1
    def select_box(image_box)
    def add_polygon_vertex(image_point)
    def finish_polygon() -> list[tuple[int, int]]
    def undo_last() -> bool
    def clear_prompt() / fit_view() / zoom(factor, view_point=None)
```

- `set_image` nepostojeći fajl → `FileNotFoundError`; `image_size` vraća
  (širina, visina) u pikselima.
- `add_prompt_point` emituje `prompt_point_added(label, x, y)` i dodaje tačku u
  `canvas.prompt_builder`; u polygon režimu → `ValueError`; label van {0,1} →
  `ValueError`.
- `select_box` emituje normalizovan box; `add_polygon_vertex` + `finish_polygon`
  emituju `polygon_finished` sa listom celobrojnih tačaka.
- `undo_last` uklanja poslednji marker/box i vraća bool; `clear_prompt` resetuje
  builder i emituje `prompt_cleared`.

## `lampcutter.ui.panels` — paneli (spec 12.1)

```python
class SizePanel(QGroupBox):
    size_changed = Signal(str, float)   # reference, mm
    reference() -> "height" | "width"
    value_mm() -> float
    set_value_mm(value) / set_computed(width, height, total_height)
    # unit combo: mm/cm; prelazak mm→cm i nazad ne menja value_mm()
class MaterialPanel(QGroupBox):
    material_changed = Signal(str)
    set_materials(list[MaterialProfile]) / current_material_id() -> str
class BasePanel(QGroupBox):
    base_changed = Signal(dict)
    set_bases(list[BaseProfile]) / current_base_id() / values() -> dict
    set_clearance(planar_mm, thickness_mm)
class ContourPanel(QGroupBox):
    contour_changed = Signal(dict)
    values() -> {"input_kind", "edge_inset_mm", "kerf_mode", "simplify_tol_mm"}
class ElementsPanel(QGroupBox):
    mode_changed = Signal(str, str)   # element id, mode
    element_selected = Signal(str)
    set_elements(slots, decor) / current_element() -> (kind, id) | None
```

- `SizePanel`: `set_value_mm(250)` → `value_mm() == 250`; prelazak na cm i
  nazad čuva `value_mm()`; S/M/L dugmad postavljaju 150/200/250 mm; emituje
  `size_changed(reference, mm)`.
- `BasePanel`: izbor profila puni polja iz `BaseProfile`; `values()` vraća
  ključeve `slot_length_mm, slot_thickness_mm, tab_width_mm, tab_height_mm,
  tab_fit_mm, tab_offset_mm, corner_radius_mm`; `set_clearance` prikazuje tekst
  sa vrednostima.
- `ElementsPanel`: `set_elements` popunjava listu (slotovi pa dekor);
  `current_element()` vraća `("slot", id)` ili `("decor", id)` ili None;
  promena režima za dekor emituje `mode_changed(id, mode)`.

## `lampcutter.ui.main_window` — glavni prozor

```python
class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings | None = None, parent=None)
    image_path / last_result
    def load_image(path) / open_image_dialog()
    def current_config() -> Config
    def current_material() -> MaterialProfile
    def current_base() -> BaseProfile | None
    def current_input_kind() -> str
    def recompute() / export() / cancel() / undo() / clear_prompt()
    def _run_job(progress=None) -> PipelineResult   # poziva se u workeru
```

- `load_image` sa nepostojećim fajlom ne ruši prozor (prikazuje grešku).
- `current_config` reflektuje `ContourPanel` (`kerf_mode`, `simplify_tol_mm`,
  `edge_inset_mm` za izabrani `input_kind`).
- `recompute()` bez učitane slike ili bez prompta **ne pokreće** worker (status
  poruka); proverava se da `runner.generations.current` ostane 0.
- `undo()` poziva `canvas.undo_last`; `clear_prompt()` resetuje prompt.
- `closeEvent` ne sme da visi (worker se prekida).
- GUI testovi ne smeju zahtevati SAM 2 model; koristi se poligon alat ili se
  proverava samo stanje UI-ja.

## `lampcutter.ui.app` / CLI

- `run_gui` se ne testira (event loop).
- `lampcutter.cli.main(["gui", "--help"])` podiže `SystemExit(0)`; `--help`
  izlaz sadrži `gui`.

## Format test seta

Isti kao ranije: Python pytest fajl se upisuje u wiki kao
`artifacts/tests-phase2.py`, DSH ga umotava u JSON i zaključava.
