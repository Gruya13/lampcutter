# API ugovor — Faza 1

Dopuna ugovora iz [`api-phase0a.md`](api-phase0a.md) i [`api-phase0b.md`](api-phase0b.md).
Faza 1 pokriva slotove za fotografije, dekor, štampu i šablone (spec 9, 13.1).

Konvencije: koordinate u mm su **apsolutne** (iz slike, kao u 0a/0b); y nadole.
Print sheet i SVG koriste **isti koordinatni početak** — gornji levi ugao
nominalne konture + `svg_margin_mm`.

## Novo u `lampcutter.config`

```python
print_order: str = "cut_then_print"     # ili "print_then_cut"
slot_photo_min_dpi: float = 150.0
decor_ink_color: str = "#000000"
registration_mark_size_mm: float = 5.0        # PROVIZORNO
registration_mark_offset_mm: float = 5.0      # PROVIZORNO
registration_mark_circle_radius_mm: float = 1.0  # PROVIZORNO
slot_solidity_min: float = 0.5                # PROVIZORNO
slot_overlap_max: float = 0.1                 # PROVIZORNO
slot_min_area_mm2: float = 50.0               # PROVIZORNO
decor_upsample: int = 2
```

- Nepoznat `print_order` → `ValueError`; `slot_solidity_min` mora biti u (0, 1];
  `slot_overlap_max` u [0, 1]; `slot_min_area_mm2 > 0`.

## `lampcutter.core.slots` (GeoJSON I/O, spec 5, 9.2)

```python
SCHEMA_VERSION = 1
ROUND_MM = 0.001

def round_polygon(polygon, decimals=3): ...
def polygon_to_geojson(polygon, decimals=3) -> dict: ...
def polygon_from_geojson(data) -> shapely.Polygon: ...
def scale_to_geojson(scale) -> dict / scale_from_geojson(data) -> ScaleInfo
def cut_geometry_to_geojson(cut_geometry) -> dict / cut_geometry_from_geojson(data) -> CutGeometry
def slot_to_geojson(slot) -> dict / slot_from_geojson(data) -> PhotoSlot
def decor_to_geojson(element) -> dict / decor_from_geojson(data) -> DecorElement
def template_to_geojson(template) -> dict
def template_from_geojson(data) -> LampTemplate
def save_template(template, path) -> Path
def load_template(path) -> LampTemplate
def validate_slot_mask(mask, mm_per_px, existing_slots=None, config=None) -> list[str]
```

- GeoJSON koordinate su zaokružene na 0,001 mm; **round-trip tolerancija 0,001 mm**
  za sve poligone (kontura, slotovi, dekor).
- `template_to_geojson` sadrži `"schema": 1` i sve delove šablona
  (outline, slots, decor, base, material, scale, input_kind).
- `template_from_geojson` sa nepoznatom šemom → `ValueError`.
- `save_template`/`load_template` su round-trip za `.lamptpl`.
- `validate_slot_mask` vraća listu upozorenja ("pobegao klik", spec 7.3):
  - površina maske < `config.slot_min_area_mm2` → upozorenje;
  - solidnost (površina / površina konveksnog omotača najveće konture) <
    `config.slot_solidity_min` → upozorenje;
  - preklapanje sa datim postojećim slotovima > `config.slot_overlap_max`
    (udeo nove površine) → upozorenje;
  - prazna maska → `["maska je prazna"]`; ispravna maska → `[]`.

## `lampcutter.core.decor` (spec 9.1, 9.3)

```python
class DecorError(ValueError): ...
def crop_zone(image, zone) -> np.ndarray: ...
def threshold_mask(image, zone, mode="luminance", threshold=None) -> tuple[np.ndarray, float]: ...
def decor_polygons_from_mask(mask, mm_per_px, origin_px=(0, 0), config=None) -> list[Polygon]: ...
def decor_from_threshold(image, zone, scale, mode="luminance", threshold=None, config=None) -> list[Polygon]: ...
def decor_from_mask(mask, scale, config=None) -> list[Polygon]: ...
def element_from_polygon(element_id, polygon, source="threshold", mode="engrave") -> DecorElement
def engrave_polygons(elements) -> list[Polygon]
def print_elements(elements) -> list[DecorElement]
def validate_decor_in_outline(elements, outline_nominal, margin_mm) -> list[str]
def decor_warnings(elements, outline_nominal, material, margin_mm, config=None) -> list[str]
```

- `threshold_mask` vraća masku **u koordinatama zone** i korišćeni prag.
  `mode="luminance"`: pikseli tamniji od praga (ako je `threshold=None`, Otsu
  adaptivni); `mode="color"`: pikseli udaljeni od medijane boje zone.
  Nepoznat režim → `ValueError`; prazna zona → `ValueError`.
- `decor_from_threshold` vraća listu poligona u **apsolutnim mm** slike
  (translirani za `zone` origin), sortirano po površini opadajuće. Sintetička
  slika sa tamnim kvadratom 20×20 mm u zoni → jedan poligon ≈ 20×20 mm na
  tačnoj poziciji (tolerancija 0,2 mm).
- `engrave_polygons` vraća poligone samo za `mode=="engrave"`;
  `print_elements` samo za `mode=="print"`.
- `validate_decor_in_outline`: element mora biti unutar
  `outline.buffer(-margin_mm)`; inače upozorenje sa id-em. `mode=="none"` se
  preskače; negativna margina → `ValueError`.
- `decor_warnings`: gore + upozorenje za linije tanje od `material.min_feature_mm`.

## `lampcutter.core.compose` (spec 9.1–9.4)

```python
MM_PER_INCH = 25.4
def mm_to_px(mm, dpi) -> float / px_to_mm(px, dpi) -> float
def sheet_size_mm(template, config=None) -> tuple[float, float]
def sheet_offset_mm(template, config=None) -> tuple[float, float]
def registration_mark_positions(width_mm, height_mm, config=None) -> list[tuple[float, float]]
def slot_bleed_mm(slot, config=None) -> float
def slot_bbox_mm(slot, config=None, bleed=False) -> tuple[float, float, float, float]
def slot_px_size(slot, dpi, config=None, bleed=False) -> tuple[int, int]
def slot_alpha(slot, dpi, config=None) -> PIL.Image.Image
def fit_photo(photo, target_size, fit="cover", zoom=1.0, offset_mm=(0, 0), rotation_deg=0.0, dpi=25.4) -> PIL.Image.Image
def effective_dpi(slot, photo_size, config=None) -> float
def render_photo_slot(slot, config=None, dpi=None) -> tuple[Image.Image, float]
def slots_effective_dpi(template, config=None) -> dict[str, float]
def render_print_sheet(template, config=None, dpi=None) -> Image.Image
def render_decor_png(element, dpi, config=None) -> Image.Image
def manifest_dict(template, config=None, effective_dpi=None) -> dict
def export_bundle(template, out_dir, config=None) -> ExportResult

@dataclass
class ExportResult:
    svg_path: Path
    print_sheet_path: Path | None
    photo_paths: dict[str, Path]
    decor_paths: dict[str, Path]
    manifest_path: Path | None
    effective_dpi: dict[str, float]
    sheet_size_mm: tuple[float, float]
    offset_mm: tuple[float, float]
    warnings: list[str]
```

- `sheet_size_mm` = bbox nominala + 2 × `svg_margin_mm`;
  `sheet_offset_mm` = `(svg_margin_mm - min_x, svg_margin_mm - min_y)`.
  **Poravnanje (spec 13.1):** za isti šablon, `sheet_offset_mm` mora biti
  identičan `svg_writer.origin_offset_mm(template.outline, config)` u okviru
  0,1 mm, a `sheet_size_mm` identičan `svg_writer.canvas_size_mm` (0,1 mm).
- `slot_alpha` vraća L-masku oblika slota sa bleed-om (`slot.bleed_mm` ili
  `config.print_bleed_mm`).
- `fit_photo`:
  - `cover` popunjava ceo ciljni okvir (nema providnih praznina),
    `contain` čuva celu fotografiju (može ostati providno);
  - `zoom > 0` uvećava; `offset_mm` pomera; `rotation_deg` rotira oko centra;
  - nepoznat `fit` → `ValueError`; `zoom <= 0` → `ValueError`.
- `render_photo_slot` vraća RGBA sliku oblika slota (alfa = slot + bleed) i
  efektivni DPI. `photo_XX.png` dimenzije u pikselima = mm × `print_dpi` / 25,4.
  Sintetička fotografija sa crvenim markerom: rotorana/zoomovana verzija mora
  deterministički da promeni količinu crvenih piksela u skladu sa zumom.
- `effective_dpi` = iskorišćeni pikseli fotografije po inču štampe; upozorenje
  ako je < `config.slot_photo_min_dpi` (u `export_bundle`).
- `render_print_sheet`: RGBA, transparentna pozadina, veličina =
  `sheet_size_mm` × `print_dpi`; slotovi sa fotografijom paste-ovani na svoje
  pozicije i obrezani oblikom slota; print dekor elementi popunjeni bojom; 4
  registracione oznake (ako `config.registration_marks`). U režimu
  `print_then_cut` sadrži i tanku konturu reza, u `cut_then_print` ne.
- `export_bundle` piše: `lamp_cut.svg` (cut + engrave sloj), `print_sheet.png`,
  `photo_XX_<id>.png`, `decor_XX_<id>.png`, `manifest.json`.
  `manifest.json` sadrži: `schema`, `app_version`, `generated_at`,
  `input_kind`, `material`, `base`, `scale`, `kerf_mm`, `print_dpi`,
  `print_order`, `sheet_size_mm`, `origin_offset_mm`, listu slotova
  (poligon GeoJSON, efektivni DPI) i listu dekora.
- **Dekor u SVG-u (spec 13.1):** `engrave` elementi završavaju u SVG grupi
  `id="engrave"` sa `stroke="#0000FF"` (config `engrave_color`), translirani
  istim offsetom kao cut, **bez kerf offseta** (poligon se ne širi); `print`
  elementi se **ne pojavljuju** u SVG-u, samo u print sheet-u i `decor_XX.png`.

## Test set

Format isti kao 0a/0b: Python pytest fajl se upisuje u wiki
(`artifacts/tests-phase1.py`), DSH ga umotava u JSON i zaključava.
Okruženjska nezavisnost: bez mreže, bez korisničkih profila, fajlovi u
`tmp_path`, sintetičke fotografije.
