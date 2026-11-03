# API ugovor — Faza 0b

Dopuna ugovora iz [`api-phase0a.md`](api-phase0a.md). Testovi se pišu iz
specifikacije i ovih potpisa, **ne** čitanjem koda. Faza 0b pokriva: jezičak i
prorez baze (8.3), kalibraciju kerfa (7.9), PipelineCache (4.3), kompletan
`mask_ops` (`refine_edge`, 7.4) i integraciju u pipeline/CLI.

Konvencije su iste kao u 0a (bool maske, y nadole, `bbox_px` ekskluzivan,
mm je `float`). Greške validacije su `ValueError` ili podklasa; poruke na srpskom.

## `lampcutter.core.geometry` — novo u 0b

```python
class TabError(GeometryError): ...

@dataclass(frozen=True)
class SlotClearance:
    effective_slot_length_mm: float
    planar_clearance_mm: float
    thickness_clearance_mm: float
    warnings: tuple[str, ...]

def bottom_contact(polygon, flat_tolerance_mm: float = 0.2) -> tuple[float, float, float]: ...
def add_tab(nominal, base: BaseProfile) -> shapely.Polygon: ...
def effective_slot_length(base: BaseProfile) -> float: ...
def slot_clearance(base: BaseProfile, material: MaterialProfile) -> SlotClearance: ...
```

- `bottom_contact` vraća `(min_x, max_x, y_bottom)`; `y_bottom = max y` konture,
  a kontakt su tačke sa `y >= y_bottom - flat_tolerance_mm`. Ako ih je manje od
  2 ili je širina kontakta 0 → `TabError` ("donja ivica nije ravna").
  `flat_tolerance_mm <= 0` → `ValueError`.
- `add_tab`: pravougaonik širine `base.tab_width_mm + base.tab_fit_mm` i visine
  `base.tab_height_mm`, sa zaobljenim uglovima (`base.corner_radius_mm`),
  centriran na sredinu donjeg kontakta plus `base.tab_offset_mm`, unija sa telom.
  `tab_fit_mm` utiče **samo** na jezičak — širina tela se ne menja.
  Greške: `tab_width_mm + tab_fit_mm <= 0` → `TabError`; `tab_height_mm <= 0` →
  `TabError`; jezičak širi od donjeg kontakta → `TabError`; neravna donja ivica →
  `TabError`.
- **Kerf i jezičak (spec 8.3):** posle `compute_cut_geometry(..., kerf_mode="app")`
  presek `cut_path` na sredini visine jezička mora biti
  `tab_width_mm + tab_fit_mm + kerf_mm` (tolerancija 0,01 mm); presek `nominal`
  na istom mestu je `tab_width_mm + tab_fit_mm` (tolerancija 0,01 mm).
- `effective_slot_length`: `slot_length_mm + base_kerf_mm` za
  `slot_dimensions="nominal_laser_cut"`; inače `slot_length_mm`.
- `slot_clearance`:
  - `planar_clearance_mm = effective_slot_length - (tab_width_mm + tab_fit_mm)`;
  - `thickness_clearance_mm = slot_thickness_mm - material.thickness_mm`;
  - `warnings` je tuple poruka: negativan zazor → "neće ući"; zazor u ravni
    > 1,0 mm → "klima"; zazor po debljini > 0,3 mm → "klima"; debljina veća od
    proreza → "neće ući". Pozitivan zazor unutar pragova → prazan tuple.
- `prepare_nominal(polygon, config, input_kind, base=None)`: isti redosled kao
  0a; kada je `base` dat, jezičak se dodaje **pre** `simplify` (spec 8.2 korak 4
  pre koraka 5).

## `lampcutter.core.mask_ops.refine_edge` (spec 7.4)

```python
def refine_edge(image: np.ndarray, mask: np.ndarray, band_px: int) -> np.ndarray: ...
```

- `image` je `H x W x 3` uint8 RGB; `mask` je bool iste veličine.
- Vraća bool masku istog oblika; GrabCut radi samo u traci širine ~`band_px`
  oko trenutne ivice, ostalo ostaje sigurno napred/pozadina.
- `band_px <= 0` → `ValueError`; `image` bez 3 kanala → `ValueError`;
  prazna maska → vraća praznu masku.
- Na sintetičkoj slici sa čistim objektom refine ne sme drastično da promeni
  masku: IoU sa ulaznom maskom > 0,95.

## `lampcutter.core.calibrate` (spec 7.9)

```python
@dataclass(frozen=True)
class KerfMeasurement:
    nominal_mm: float
    measured_mm: float
    @property
    def kerf_mm(self) -> float: ...

def parse_sizes(value: str) -> list[float]: ...
def calibration_squares(sizes_mm, spacing_mm: float = 10.0) -> list[shapely.Polygon]: ...
def build_calibration_svg(sizes_mm, path, config=None, spacing_mm=10.0) -> pathlib.Path: ...
def compute_kerf(nominal_mm: float, measured_mm: float) -> float: ...
def average_kerf(measurements: list[KerfMeasurement]) -> float: ...
def measurements_from_lists(sizes_mm, measured_mm) -> list[KerfMeasurement]: ...
```

- `parse_sizes("20,30,40")` → `[20.0, 30.0, 40.0]`; prazna/neispravna vrednost
  → `ValueError`.
- `calibration_squares`: kvadrati poređani u niz sleva nadesno, prvi počinje u
  `(0, 0)`, razmak `spacing_mm`; svaki kvadrat je tačno `size x size`.
- `build_calibration_svg`: SVG sa svim kvadratima u jednom sloju `cut-outer`,
  **bez** kerf kompenzacije (nominalne dimenzije); fajl je validan SVG u mm
  (dimenzije = bbox + 2 `svg_margin_mm`). Vraća putanju.
- `compute_kerf(20.0, 19.8)` → `0.2` (u granicama float tolerancije);
  `nominal_mm <= 0` ili `measured_mm <= 0` → `ValueError`.
- `average_kerf`: prosek `kerf_mm` po merenjima; prazna lista → `ValueError`.
- `measurements_from_lists`: dužine moraju da se poklope → inače `ValueError`.

## `lampcutter.core.cache` (spec 4.3)

```python
Stage = Literal["S1", "S2", "S3", "S4", "S5", "S6"]
STAGES: tuple[str, ...]

def mask_digest(mask: np.ndarray) -> str: ...
def polygon_digest(polygon) -> str: ...
def cut_geometry_digest(cut_geometry) -> str: ...
def config_digest(**values) -> tuple[tuple[str, str], ...]: ...

class PipelineCache:
    def __init__(self) -> None: ...
    computations: collections.Counter[str]   # broj stvarnih izračunavanja po fazi
    def get(self, stage, parts: tuple, factory: Callable[[], Any]) -> Any: ...
    def clear_from(self, stage: str) -> None: ...
    def clear(self) -> None: ...
    def __len__(self) -> int: ...
```

- `get` vraća keširanu vrednost za isti `(stage, parts)`; prvi poziv poziva
  `factory` i uvećava `computations[stage]`; kasniji pozivi ne pozivaju factory.
- `mask_digest` je determinističan: iste maske → isti digest, različite → različit.
- `polygon_digest` je determinističan za istu geometriju (tolerancija 1e-9 mm).
- `clear_from("S3")` briše S3–S6 iz keša i resetuje njihove brojače; S1/S2 ostaju.
- `clear()` briše sve.

## `lampcutter.core.pipeline` — proširenja

```python
@dataclass
class PipelineResult:
    cut_geometry: CutGeometry
    scale: ScaleInfo
    svg_path: Path
    nominal: shapely.Polygon | None
    mask_raw: np.ndarray | None
    mask_clean: np.ndarray | None
    clearance: geometry.SlotClearance | None
    debug_paths: dict[str, Path]
    warnings: list[str]

def run_pipeline(
    image_path,
    *,
    prompt=None, mask_file=None, polygon_px=None,
    config: Config | None = None,
    material: MaterialProfile,
    base: BaseProfile | None = None,
    input_kind: str = "mockup",
    height_mm: float,
    reference: str = "height",
    out_dir="izlaz",
    debug_dir=None,
    models_dir="models",
    segmenter=None,          # dependency injection za GUI i testove
    cache: PipelineCache | None = None,
    progress=None,
    cancel=None,
) -> PipelineResult: ...
```

- Kada je `base` dat, nominal uključuje jezičak (vidi `add_tab`) i
  `result.clearance` je popunjen; upozorenja iz `slot_clearance` se dodaju u
  `result.warnings`.
- `segmenter` može biti bilo koji objekat sa `set_image(np.ndarray)` i
  `predict(prompt, multimask=...)` koji vraća objekat sa `.mask` — tako se
  pipeline testira bez modela.
- **Keš invalidacija (spec 13.1):** sa istim `cache`:
  - drugi poziv sa promenjenim `material.kerf_mm` ne sme da poveća
    `cache.computations` za S1–S4; S5 i S6 se povećavaju;
  - promena prompta (ista slika) povećava S2–S6, ali ne S1 (kada je `segmenter`
    isti objekat).
- Izlaz: `<out_dir>/lamp_cut.svg`; dimenzije platna = bbox **nominala**
  (uključujući jezičak) + 2 × `svg_margin_mm`.

## `lampcutter.settings`

```python
def find_material(materials, material_id) -> MaterialProfile: ...   # KeyError ako nema
def find_base(bases, base_id) -> BaseProfile: ...                   # KeyError ako nema
def load_materials(path=None) -> list[MaterialProfile]: ...         # fallback na default
def load_bases(path=None) -> list[BaseProfile]: ...
def save_materials(materials, path=None) -> Path: ...
def save_bases(bases, path=None) -> Path: ...
```

- `load_materials(nepostojeći)` vraća ugrađene default profile.
- `save_materials` + `load_materials` round-trip čuva sva polja (test u
  `tmp_path`).
- Nepoznat id → `KeyError`.

## CLI (spec 10)

```bash
lampcutter calibrate --sizes 20,30,40 --out ./kalibracija
lampcutter calibrate --sizes 20,30,40 --measured 19.8,29.75,39.7 --material acrylic-3
lampcutter run slika.jpg --mask-file maska.png --height-mm 250 --base oval-wood --out izlaz
lampcutter benchmark --images tests/data --out benchmark_report   # prosleđuje scripts/benchmark.py
```

- `calibrate --measured` ispisuje kerf po kvadratu i prosek. Ako je dat
  `--material`, upisuje kerf u korisnički profil materijala.
- `run --base` sada zaista dodaje jezičak (u 0a se ignorisao).
- Testovi CLI-ja: mogu pozvati `lampcutter.cli.main([...])` i proveriti izlazne
  fajlove u `tmp_path`; ne menjati korisničke profile (ne slati `--material`).

## Format test seta

Isti kao u 0a: jedan JSON sa `schema`, `suite`, `author`, `entry`, `cases`
(lista id-jeva) i `source_text` (kompletan pytest fajl). Ovaj put u wiki ide
**Python fajl** (`artifacts/tests-phase0b.py`), a DSH ga umotava u JSON i
zaključava.
