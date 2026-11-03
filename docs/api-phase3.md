# API ugovor — Faza 3 (projekti, profili, šabloni kroz UI, i18n)

Dopuna ugovora iz 0a/0b/1/2. Faza 3 pokriva (spec 12.3, 6.2, 6.3, 16):
`.lampproj` projekat, uređivače profila materijala i baze, čuvanje/otvaranje
`.lamptpl` šablona kroz UI, dodavanje slotova/dekora iz poligona i i18n hook.

## `lampcutter.core.project` (`.lampproj`, spec 12.3)

```python
SCHEMA_VERSION = 1
VALID_REFERENCES = ("height", "width")
VALID_KERF_MODES = ("app", "lightburn")
VALID_INPUT_KINDS = ("mockup", "photo")

@dataclass
class ProjectState:
    image_path: Path | None = None
    prompt: Prompt | None = None
    polygon_px: list[tuple[int, int]] = []
    reference: str = "height"
    height_mm: float = 200.0
    material_id: str = "acrylic-3"
    base_id: str | None = "oval-wood"
    kerf_mode: str = "app"
    input_kind: str = "mockup"
    edge_inset_mm: dict[str, float] = {"mockup": 0.5, "photo": 0.8}
    simplify_tol_mm: float = 0.03
    template_path: Path | None = None

def project_to_dict(state, base_dir=None) -> dict
def project_from_dict(data, base_dir=None) -> ProjectState
def save_project(state, path) -> Path
def load_project(path) -> ProjectState
```

- `ProjectState` validacije: nepoznat `reference` / `kerf_mode` / `input_kind` →
  `ValueError`; `height_mm <= 0` → `ValueError`.
- `save_project`/`load_project` su **round-trip** (sva polja, prompt points/labels/
  box, polygon); putanje unutar foldera projekta se čuvaju **relativno**, a
  putanje van foldera ostaju apsolutne (test: projekat u `tmp_path` sa slikom u
  istom folderu → JSON sadrži samo ime fajla; slika van foldera → apsolutna putanja).
- `schema` u JSON-u je 1; bilo koja druga vrednost → `ValueError`.
- **Reprodukcija izlaza (DoD):** dva `run_pipeline` poziva sa istim ulazima
  (mask_file + isti config/materiali) daju **identičan** `lamp_cut.svg` (isti
  sha256), pa se projekat koji čuva te ulaze reprodukuje. Test može:
  1. prvi put: pipeline sa `mask_file`, sačuvaj `sha256` SVG-a;
  2. `ProjectState` sa istim parametrima → `save_project`/`load_project`;
  3. drugi put iz `ProjectState` → isti `sha256`.
  (Koristi `tests/data/ref/ploca.png` i `tests/data/ploca.png`, bez modela.)

## `lampcutter.ui.dialogs` (spec 6.2, 6.3, 12.1)

```python
class MaterialEditorDialog(QDialog):
    def __init__(self, material: MaterialProfile, parent=None)
    id_edit / name_edit / thickness_spin / kerf_spin / min_feature_spin / notes_edit
    def edited_material() -> MaterialProfile

class BaseEditorDialog(QDialog):
    def __init__(self, base: BaseProfile, parent=None)
    name_edit / slot_length / slot_thickness / slot_dimensions / base_kerf /
    tab_width / tab_height / tab_fit / tab_offset / corner_radius
    def edited_base() -> BaseProfile
```

- `edited_material` vraća novi `MaterialProfile` sa **istim id-jem**, izmenjenim
  vrednostima iz polja (naziv prazan → fallback na id).
- `edited_base` analogno; `slot_dimensions` daje `"measured"` ili
  `"nominal_laser_cut"`.
- Dijalozi se ne izvršavaju (`exec`) u testovima — proverava se `edited_*`.

## `lampcutter.ui.i18n` (spec 0.2.8, 12.4)

```python
def translations_dir() -> Path
def available_languages() -> list[str]
def load_translations(app, language: str | None = None) -> QTranslator
```

- Bez `.qm` fajlova: `available_languages() == []`, `load_translations(app)` vraća
  translator i **ne pada**; nepostojeći jezik takođe ne pada (koriste se izvorni
  stringovi).
- `translations_dir()` je apsolutna putanja (može ne postojati).

## `lampcutter.ui.canvas` — dopuna

```python
def load_prompt(prompt) -> None      # očisti pa dodaj tačke/labele/box
def load_polygon(points) -> None     # reset pa dodaj temena i nacrtaj
```

- `load_prompt` postavlja isti sadržaj u `canvas.prompt_builder`
  (`to_prompt()` daje iste tačke/labele/box).
- `load_polygon` popunjava `canvas.polygon_tool.points`; `finish_polygon()` vraća
  iste celobrojne tačke.

## `lampcutter.ui.panels` — dopuna

```python
class SizePanel:  def set_reference(reference) -> None
class MaterialPanel: def select_material(material_id) -> None
class BasePanel: def select_base(base_id | None) -> None
                 def set_values(values: dict) -> None
class ContourPanel: def set_values(values: dict) -> None
```

- `set_values` postavlja polja bez petlje signala (koristi se pri otvaranju
  projekta); `values()` posle toga vraća iste vrednosti.

## `lampcutter.ui.main_window` — dopuna

```python
class MainWindow:
    template: LampTemplate | None
    project_path / template_path / last_export
    def current_project_state() -> ProjectState
    def apply_project_state(state) -> None
    def save_project() / save_project_dialog() / open_project(path)
    def open_project_dialog() / save_template_dialog() / open_template_dialog()
    def _load_template_file(path) -> None
    def add_element_from_polygon(kind, decor_mode="engrave") -> None
    def remove_selected_element() / clear_elements()
    def _on_element_mode(element_id, mode) -> None
    def _edit_material() / _edit_base()
```

- `current_project_state` čita sliku, prompt/poligon, veličinu/referencu,
  material_id/base_id, kerf/input_kind/simplify iz panela i `template_path`.
- `apply_project_state`: učitava sliku, prompt/poligon, postavlja panele
  (uključujući `input_kind`/`kerf_mode`); projekat sa šablonom učitava i šablon.
- **DoD profil materijala:** `_edit_material` (dijalog se monkeypatch-uje da vrati
  `Accepted`) menja profil u `settings.materials`, upisuje ga kroz
  `save_materials` i `current_material().kerf_mm` je nova vrednost.
- `add_element_from_polygon("slot")` sa završenim poligonom i postavljenim
  `last_result` dodaje `PhotoSlot` u `window.template.slots`;
  `("decor", "engrave")` dodaje `DecorElement` sa `mode="engrave"`; bez
  `last_result` ili bez poligona postavlja `last_error` i ne pada.
- `remove_selected_element` uklanja element izabran u `elements_panel`;
  `clear_elements` prazni listu; `_on_element_mode` menja režim dekora.
- `_load_template_file` učitava `.lamptpl` i postavlja `window.template` +
  `template_path`; loš fajl → `last_error`, bez pada.
- Bez modalnih dijaloga u greškama (status bar + `last_error`), da offscreen
  testovi ne blokiraju.

## Format test seta

Isti kao ranije: Python pytest fajl se upisuje u wiki kao
`artifacts/tests-phase3.py`, DSH ga umotava u JSON i zaključava.
