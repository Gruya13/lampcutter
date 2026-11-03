# API ugovor — Faza 0a

Ovaj dokument je ugovor između implementacije i **nezavisnog test seta**. Testovi
se pišu iz specifikacije (`LAMPCUTTER_SPEC.md`) i ovih potpisa, **ne** čitanjem
koda. Ako implementacija ne ispunjava ono što ovde piše, to je nalaz — ne test
koji se prilagođava.

Autor test seta: **agy**. Zaključavanje: `agent-probe/test-lock.mjs`.

## Konvencije

- Sve maske su `np.ndarray` dtype `bool`, oblik `(height, width)`, `True` = lampa.
- y raste nadole (numpy indeks i SVG konvencija); nema flipovanja.
- `bbox_px` je `(left, top, right, bottom)`, desna i donja granica **ekskluzivne**
  (numpy slicing): `right - left` je širina u pikselima.
- `bbox_nominal_mm` je `shapely` `bounds` redosled: `(minx, miny, maxx, maxy)`.
- Sve u millimetrima je `float`; tolerancije u testovima treba da budu
  eksplicitne (npr. `1e-6` za tačnu aritmetiku, `0.01` mm za geometriju).
- Greške validacije su `ValueError` (ili podklasa: `GeometryError`,
  `VectorizeError`); poruke su na srpskom.

## `lampcutter.config`

```python
@dataclass
class Config:
    sam_variant: str = "auto"          # auto/tiny/small/base_plus/large
    device: str = "auto"               # auto/cuda/mps/cpu
    max_side_px: int = 2048
    mask_min_component_frac: float = 0.001
    mask_hole_min_area_mm2: float = 4.0
    mask_smooth_sigma_px: float = 2.0
    potrace_turdsize: int = 20
    potrace_alphamax: float = 1.0
    potrace_opttolerance: float = 0.2
    curve_sample_tol_mm: float = 0.05
    kerf_mode: str = "app"             # app | lightburn
    edge_inset_mm: dict[str, float]    # {"mockup": 0.5, "photo": 0.8} — PROVIZORNO
    simplify_tol_mm: float = 0.03
    engrave_margin_mm: float = 1.5
    print_dpi: int = 600
    print_bleed_mm: float = 0.3
    registration_marks: bool = True
    svg_margin_mm: float = 5.0
    cut_stroke: str = "#FF0000"
    cut_stroke_width_mm: float = 0.1
    engrave_color: str = "#0000FF"
    min_edge_mm: float = 0.02
    thin_feature_min_area_mm2: float = 0.5
    vectorize_backend: str = "potrace"  # potrace | cv2
    vectorize_upsample_threshold_px: int = 1500
    min_resolution_px: int = 1000
```

- `Config()` mora da uspe sa podrazumevanim vrednostima.
- `config.edge_inset("mockup")` → `0.5`; `edge_inset("photo")` → `0.8`;
  nepoznat kind → `ValueError`.
- Nepoznat `kerf_mode` / `sam_variant` / `device` / `vectorize_backend` u
  konstruktoru → `ValueError`.
- `Config.from_mapping({...})` odbija nepoznate ključeve (`ValueError`).

## `lampcutter.models`

```python
@dataclass(frozen=True)
class Prompt:
    points: tuple[tuple[int, int], ...] = ()
    labels: tuple[int, ...] = ()
    box: tuple[int, int, int, int] | None = None
    @property
    def is_empty(self) -> bool: ...

@dataclass
class SegmentationResult:
    mask: np.ndarray       # bool H x W
    score: float
    all_candidates: list[np.ndarray]

@dataclass(frozen=True)
class ScaleInfo:
    mm_per_px: float
    reference: str                      # "height" | "width"
    reference_mm: float
    bbox_px: tuple[int, int, int, int]
    @property
    def width_mm(self) -> float: ...
    @property
    def height_mm(self) -> float: ...

@dataclass(frozen=True)
class MaterialProfile:
    id: str
    name: str
    thickness_mm: float
    kerf_mm: float
    min_feature_mm: float = 1.5
    notes: str = ""

@dataclass
class CutGeometry:
    nominal: shapely.Polygon
    cut_path: shapely.Polygon
    kerf_mm: float
    area_mm2: float
    bbox_nominal_mm: tuple[float, float, float, float]
```

Validacije:
- `Prompt`: `len(points) != len(labels)` → `ValueError`; labela van {0,1} →
  `ValueError`; `box` sa `x1 <= x0` ili `y1 <= y0` → `ValueError`.
- `ScaleInfo`: `mm_per_px <= 0` ili `reference_mm <= 0` → `ValueError`;
  `bbox_px` sa `right <= left` ili `bottom <= top` → `ValueError`.
- `width_mm == (right - left) * mm_per_px`, analogno `height_mm`.

## `lampcutter.core.mask_ops`

Sve funkcije uzimaju i vraćaju `bool` masku istog oblika.

| funkcija | ponašanje |
|---|---|
| `components(mask) -> list[np.ndarray]` | komponente (8-konektivnost), sortirane po površini **opadajuće** |
| `count_components(mask) -> int` | broj komponenti |
| `largest_component(mask) -> np.ndarray` | samo najveća; prazna maska → prazna maska |
| `fill_holes(mask) -> np.ndarray` | popunjava sve unutrašnje rupe (spoljna kontura ostaje) |
| `morph_close(mask, radius_px) -> np.ndarray` | eliptični kernel; `radius_px == 0` → kopija |
| `smooth(mask, sigma) -> np.ndarray` | Gaussian pa prag 0,5; `sigma == 0` → kopija |
| `cut_at_line(mask, y_px) -> np.ndarray` | zadržava redove `< y_px`, čisti `>= y_px` (donja ivica ravna) |
| `remove_stand(mask, line) -> np.ndarray` | ekvivalentno `cut_at_line` |
| `polygon_to_mask(points, shape) -> np.ndarray` | rasterizacija poligona; manje od 3 tačke → `ValueError` |
| `clean_mask(mask, config) -> np.ndarray` | `smooth → largest_component → morph_close(1) → fill_holes` |

## `lampcutter.core.scale`

```python
def mask_bbox_px(mask) -> tuple[int, int, int, int]: ...
def compute_scale(mask, reference, reference_mm, aspect_warn_ratio=10.0) -> ScaleInfo: ...
def compute_scale_from_points(p1, p2, known_mm) -> float: ...
```

- `compute_scale`: `mm_per_px = reference_mm / (bbox visina ili širina u px)`.
  Prazna maska → `ValueError`; nepoznat `reference` → `ValueError`;
  `reference_mm <= 0` → `ValueError`.
- Upozorenje `SuspiciousAspectRatioWarning` kada je odnos strana > 10 ili < 1/10.
- `compute_scale_from_points`: `known_mm / udaljenost_px`; iste tačke → `ValueError`.

## `lampcutter.core.vectorize`

```python
class VectorizeError(ValueError): ...
def vectorize_mask(mask, scale: ScaleInfo, config: Config) -> shapely.Polygon: ...
def contour_to_mm(contour, mm_per_px, min_edge_mm=0.0) -> shapely.Polygon: ...
def clean_ring(points, min_edge_mm) -> list[tuple[float, float]]: ...
```

- `vectorize_mask` vraća **najveći** validan `Polygon` u mm (y nadole), bez
  samopreseka. Prazna maska → `VectorizeError`.
- `contour_to_mm`/poligon mora imati bar 3 različite tačke.
- `clean_ring` uklanja uzastopne tačke bliže od `min_edge_mm`; vraća bar 0 tačaka
  (za manje od 3 tačke — poziva se `VectorizeError` u `contour_to_mm`).
- Sintetička maska savršenog kruga (dovoljno velika, npr. 2000 px) mora dati
  poligon čije je odstupanje od idealnog kruga < 0,05 mm po specifikaciji 7.6 —
  pri rezoluciji koju sam test izabere; u testu **napiši izabranu rezoluciju i
  izračunatu toleranciju**, ne pretpostavku.

## `lampcutter.core.geometry`

```python
class GeometryError(ValueError): ...
class ThinFeatureWarning(UserWarning): ...

def ensure_valid(polygon) -> shapely.Polygon: ...
def ensure_single_polygon(polygon) -> shapely.Polygon: ...
def fill_holes(polygon) -> shapely.Polygon: ...
def apply_edge_inset(polygon, inset_mm) -> shapely.Polygon: ...
def simplify(polygon, tolerance_mm) -> shapely.Polygon: ...
def clean_ring(points, min_edge_mm) -> list[tuple[float, float]]: ...
def clean_polygon_edges(polygon, min_edge_mm) -> shapely.Polygon: ...
def find_thin_regions(polygon, min_feature_mm) -> shapely.Geometry: ...
def check_min_feature(polygon, min_feature_mm, warn=True, min_area_mm2=0.5) -> shapely.Geometry: ...
def apply_kerf(nominal, kerf_mm, kerf_mode="app") -> shapely.Polygon: ...
def prepare_nominal(polygon, config, input_kind) -> shapely.Polygon: ...
def compute_cut_geometry(nominal, material, kerf_mode="app", min_edge_mm=0.02) -> CutGeometry: ...
```

Obavezno (specifikacija 8.1/8.2/13.1):
- **Kerf**: nominalni kvadrat 100×100 mm, `kerf = 0.2`, `kerf_mode="app"` →
  `cut_path` bbox `(-0.1, -0.1, 100.1, 100.1)` (tolerancija 0.01 mm), a
  `nominal` bbox ostaje `(0, 0, 100, 100)`.
- `kerf_mode="lightburn"` → `cut_path` identičan `nominal` (bez offseta).
- `kerf_mm = 0` → `cut_path` identičan `nominal`.
- `fill_holes` uklanja unutrašnje rupe.
- `apply_edge_inset` sa 0 → nepromenjen poligon; negativan inset → `ValueError`.
- `ensure_valid` popravlja nevalidan poligon; ako nema poligona → `GeometryError`.
- `compute_cut_geometry` popunjava `area_mm2` (površina **nominala**) i
  `bbox_nominal_mm` (bounds nominala).
- `find_thin_regions` za oblik sa "vratom" tanjim od `min_feature_mm` vraća
  nepraznu geometriju; za konveksan oblik vraća praznu geometriju.

## `lampcutter.core.svg_writer`

```python
def canvas_size_mm(geometry: CutGeometry, config: Config) -> tuple[float, float]: ...
def origin_offset_mm(geometry: CutGeometry, config: Config) -> tuple[float, float]: ...
def polygon_path_data(polygon, dx=0.0, dy=0.0) -> str: ...
def write_cut_svg(geometry, path, config, engrave=None) -> pathlib.Path: ...
def read_svg_size_mm(path) -> tuple[float, float]: ...
def validate_svg(path, expected_width_mm, expected_height_mm, tolerance_mm=1e-3) -> None: ...
```

- SVG je validan XML sa `width` i `height` u **mm** i `viewBox` u istim brojevima.
- Platno = bbox **nominalne** geometrije (pre kerf offseta) + `2 * svg_margin_mm`
  sa svake strane.
- Koordinatni početak: gornji levi ugao nominalnog bbox-a ide na
  `(svg_margin_mm, svg_margin_mm)`; cut path se translira istim pomakom.
- Grupa `id="cut-outer"`, `fill="none"`, `stroke="#FF0000"` (iz `config.cut_stroke`),
  `stroke-width` = `config.cut_stroke_width_mm`.
- Putanja sadrži samo `M`, `L`, `Z`, koordinate zaokružene na 3 decimale; bez
  `transform` atributa, bez teksta.
- `write_cut_svg` na kraju sam poziva `validate_svg`.
- `read_svg_size_mm` vraća `(width, height)` u mm; `validate_svg` baca
  `ValueError` ako se razlikuju više od tolerancije.

## `lampcutter.core.io_utils`

```python
def load_image(path, min_resolution_px=1000) -> PIL.Image.Image: ...
def file_sha256(path) -> str: ...
def save_png(image, path, dpi) -> pathlib.Path: ...
def to_working_size(image, max_side) -> tuple[PIL.Image.Image, float]: ...
def mask_to_original(mask, factor, original_size) -> np.ndarray: ...
def image_to_array(image) -> np.ndarray: ...
def array_to_image(array) -> PIL.Image.Image: ...
```

- `load_image` primenjuje EXIF orijentaciju, vraća RGB; duža strana < prag →
  upozorenje `LowResolutionWarning` (slika se i dalje vraća); nepostojeći fajl →
  `FileNotFoundError`.
- `to_working_size`: duža strana > `max_side` → umanji proporcionalno i vrati
  `factor = working/original`; ako ne treba umanjivanje → `factor == 1.0`.
- `mask_to_original`: resize maske na `original_size = (width, height)`
  nearest susedom; ako je već te veličine, vraća kopiju.
- `file_sha256` je SHA256 bajtova fajla; `save_png` upisuje DPI metapodatak.

## `lampcutter.core.device` (bez GPU, bez instaliranog torch-a)

```python
def torch_available() -> bool: ...
def pick_device(preference="auto") -> str: ...        # auto → cuda → mps → cpu
def pick_variant(device, vram_gb=None, ram_gb=None) -> str: ...
def fallback_variants(variant) -> list[str]: ...
def is_out_of_memory(error) -> bool: ...
def load_with_fallback(loader, variants, device, on_fallback=None) -> tuple[Any, str, str]: ...
```

- Na mašini bez torch-a: `pick_device("auto") == "cpu"`, `torch_available()` False.
- `pick_variant("cpu") == "tiny"`; `pick_variant("cuda", vram_gb=4.0) == "small"`;
  `pick_variant("mps") == "base_plus"`; nepoznat uređaj → `ValueError`.
- `fallback_variants("base_plus") == ["base_plus", "small", "tiny"]`;
  `fallback_variants("tiny") == ["tiny"]`; nepoznata varijanta → `ValueError`.

## `lampcutter.core.segmentation` (bez modela)

```python
def mask_from_file(path, target_size=None) -> np.ndarray: ...
class Segmenter:
    @staticmethod
    def predict_multimask_rule(prompt: Prompt) -> bool: ...
```

- `mask_from_file`: PNG → bool maska pragom > 127; `target_size = (width, height)`
  → nearest resize; nepostojeći fajl → `FileNotFoundError`.
- `predict_multimask_rule`: tačno jedna tačka **i** bez okvira → `True`; inače `False`.
- `Segmenter(...).predict(...)` bez instaliranog SAM 2 podiže
  `lampcutter.core.device.ModelUnavailableError` (ne `ImportError`).

## Format test seta (`cases.json`)

Test set je **jedan JSON fajl** koji se zaključava:

```json
{
  "schema": 1,
  "suite": "phase0a",
  "author": "agy",
  "entry": "test_phase0a_spec.py",
  "cases": [{"id": "mask_ops/largest_component"}],
  "source": "import numpy as np\n\ndef test_x():\n    ...\n"
}
```

- `cases` je lista id-jeva (za brojanje i izveštaj; izvršava se `source`).
- `source` je kompletan `pytest` fajl kao JSON string (escapovane nove linije).
  Runner ga upisuje u `.test-run/<entry>` i pokreće `pytest`.
- Testovi smeju da importuju: `numpy`, `shapely`, `cv2`, `PIL`, `pytest`,
  `lampcutter.*`. Ne smeju da pristupaju mreži; privremene fajlove pišu u
  `tmp_path`.
- Svaki `case.id` treba da odgovara bar jednom testu u `source`.

## Komande

```bash
# lint i testovi
uv run ruff check .
uv run pytest

# zaključan test set (posle prijema iz wiki-ja)
node agent-probe/test-lock.mjs lock tests/cases/phase0a.json --by agy --require-git --wiki
node agent-probe/test-lock.mjs check tests/cases/phase0a.json --require-git
uv run python scripts/run_cases.py tests/cases/phase0a.json
```
