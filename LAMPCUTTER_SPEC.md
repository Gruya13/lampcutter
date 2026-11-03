# Lamp Cutter AI Asistent: Konsolidovana tehnička specifikacija (v2.0)

Ovaj dokument je jedini izvor istine za inicijalizaciju i implementaciju projekta. Objedinjuje prvobitnu dokumentaciju, tehničku specifikaciju (revizije 1.0, 1.1, 1.2) i naknadni pregled rizika. Gde se nešto menjalo tokom razrade, ovde je upisano **konačno** rešenje.

---

## 0. Uputstvo za implementacionog agenta

### 0.1 Kontekst u jednoj rečenici
Korisnik pravi personalizovane akrilne lampe (laserski sečen akril sa UV štampom i gravurom, umetnut u LED postolje). Aplikacija pretvara sliku dizajna u (a) SVG za sečenje u LightBurn-u u stvarnim milimetrima, (b) fajlove za UV štampu fotografija i (c) opcioni sloj gravure.

### 0.2 Pravila rada
1. **Radi strogo po fazama iz odeljka 16.** Ne prelazi u sledeću fazu dok kapija (gate) prethodne nije ispunjena ili je korisnik izričito odobrio nastavak.
2. **Jezgro (`lampcutter.core`) nema zavisnosti od Qt-a.** Sve funkcije su čiste (ulaz → izlaz), bez globalnog stanja osim keširanog modela.
3. **Sve što je označeno kao PROVIZORNO (odeljak 17) ne upisuj kao konačnu podrazumevanu vrednost dok je ne potvrdi eksperiment ili benchmark.** Čuvaj ih u `config.py` sa komentarom `# PROVISIONAL`.
4. **Aplikacija mora da radi potpuno offline** (odeljak 11.3). Nikakvi mrežni pozivi u runtime kodu.
5. **Jedinice:** u kodu i fajlovima koordinate su u **milimetrima** (float), y-osa na dole (SVG konvencija), osim u pikselskim fazama koje su to izričito u imenu (`*_px`).
6. **Pitaj korisnika (ne pogađaj)** kada: ne postoje test fotografije, kada se meri fizički rez, kada vrednost zavisi od njegove mašine (kerf, prorez baze, debljina materijala).
7. **Svaka faza završava sa:** radnim kodom, testovima koji prolaze (`pytest`), kratkim `CHANGELOG.md` zapisom i listom onoga što korisnik treba ručno da proveri (npr. uvoz u LightBurn, probni rez).
8. Piši kod na engleskom (identifikatori, docstring-ovi), korisničke poruke i UI tekstove na srpskom (latinica), kroz `QTranslator` (i18n spremno za druge jezike).
9. Fiksiraj verzije zavisnosti pri inicijalizaciji (lock fajl). Zavisnosti objavljene u poslednjih 14 dana ne koristiti bez razloga.

### 0.3 Redosled prvih koraka
1. Inicijalizuj repozitorijum (odeljak 4.1), `pyproject.toml`, `pytest`, linter (`ruff`), CI skriptu.
2. **Faza E:** eksperiment sa sjajem (odeljak 16). Ne piši `segmentation.py` pre nego što eksperiment da preporuku strategije.
3. Zatim Faza 0a, 0b, itd.

---

## 1. Svrha i obim

### 1.1 Funkcionalnosti
Za zadatu sliku dizajna lampe aplikacija:

1. **Izdvaja konturu lampe** (bez postolja i pozadine) pomoću SAM 2 sa korisničkim promptom (tačke/okvir) ili iz gotove maske.
2. **Vektorizuje konturu** u SVG u mm, uz kerf kompenzaciju i dodat jezičak za postolje.
3. **Izdvaja slotove za fotografije** (proizvoljnog oblika) i **dekor elemente** (tekst, ornamenti), pri čemu korisnik za svaki dekor element bira **gravura** ili **štampa**.
4. **Izvozi** `.svg` za LightBurn (sečenje + gravura) i `.png` fajlove za UV štampu (slotovi, print sheet).
5. Podržava **dva toka rada**: izvlačenje iz gotovog dizajna (Tok A) i šablon u koji se naknadno ubacuju fotografije klijenta (Tok B).

### 1.2 Van obima (v1)
Potpuno automatsko prepoznavanje lampe bez korisnika, 3D rekonstrukcija, direktno slanje na laser, više lampi na jednoj slici, DXF izlaz, sečenje unutrašnjih otvora (u v1 samo spoljna kontura), ručna četkica za maske (v1.1; u v1 su `--mask-file` i poligon alat).

---

## 2. Sažetak odluka

| Tema | Odluka |
|---|---|
| Laserski softver | LightBurn. SVG u mm, jedan sloj po boji: sečenje `#FF0000`, gravura `#0000FF`. |
| Kerf | Zavisi od materijala: profili materijala + kalibracioni test. `kerf_mode`: `app` (offset radi aplikacija) ili `lightburn` (izvoz nominalne konture). |
| Konture | Samo spoljna kontura. Svi unutrašnji otvori se popunjavaju. |
| Oblici fotografija | Proizvoljni (srce, silueta, krug...). Model slotova u mm, ne četvorouglovi. |
| Tokovi rada | Tok A (iz gotovog dizajna) i Tok B (šablon + naknadne fotografije). |
| Ulaz | Mockup/render i stvarna fotografija. Prekidač `input_kind` menja samo polazne vrednosti. |
| Dekor (tekst, ornamenti) | Po elementu: `engrave` / `print` / `none`. |
| Postolje | Dimenzije baze se podešavaju u UI (profili baze), nisu zadate unapred. |
| Veličina lampe | Ručni unos u UI (referentna strana, vrednost, jedinica). |
| Hardver | Mac Apple Silicon (MPS) i računar sa RTX 3050 4 GB (CUDA). |
| Modeli | Svi lokalno; aplikacija radi bez interneta posle instalacije. |
| Mask fallback | `--mask-file` u CLI-ju i poligon alat u GUI-ju su deo v1. |

---

## 3. Pretpostavke o ulazu

| Pretpostavka | Detalj | Ako nije ispunjeno |
|---|---|---|
| Frontalni snimak | Kamera približno normalno na ravan lampe | Upozorenje; opciona korekcija perspektive (8.4) |
| Jasno odvajanje lampe od pozadine | Kontrast ili jednobojna pozadina | Negativne tačke / okvir / poligon alat / `--mask-file` |
| Poznata jedna stvarna dimenzija | Visina ili širina izrezanog dela u mm | Obavezno polje; bez njega izvoz u pikselima uz upozorenje |
| Formati | JPG, PNG, WEBP (HEIC opciono) | Jasna poruka o grešci |
| Rezolucija | Preporuka > 1500 px po dužoj strani | Upozorenje < 1000 px |

EXIF orijentacija se uvek primenjuje (`PIL.ImageOps.exif_transpose`).

**Karakteristike primera (3 priložena dizajna, svi mockupi):**
- Kontura je unija oblika srca/siluete/ruže; ima uska grla (npr. "vratovi" između glava na porodičnom portretu).
- Slotovi za fotografije: jedan veliki (skoro cela površina), četiri srca, jedno srce sa mrežastim okvirom.
- Ornamenti i tekst su gravura ili štampa i ne ulaze u sečenje, osim ako ih korisnik označi kao gravuru.
- Ivica **svetli** (glow), pa maska lako izađe izvan prave ivice akrila.
- **Postolje sakriva donji deo** ploče; donja ivica je ravna. Jezičak koji ulazi u prorez baze nikad nije vidljiv na slici.

---

## 4. Arhitektura

### 4.1 Struktura projekta

```
lampcutter/
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── models/                     # checkpointi + manifest.json (SHA256)
├── experiments/
│   └── glow_experiment.py      # Faza E
├── scripts/
│   ├── benchmark.py
│   └── fetch_models.py         # samo build-time preuzimanje modela
├── src/lampcutter/
│   ├── __init__.py
│   ├── config.py               # dataclass-ovi i podrazumevane vrednosti
│   ├── models.py               # tipovi podataka (odeljak 5)
│   ├── settings.py             # AppSettings, profili (platformdirs)
│   ├── core/
│   │   ├── io_utils.py
│   │   ├── device.py           # izbor uređaja i varijante modela, OOM lanac
│   │   ├── segmentation.py     # SAM 2 wrapper
│   │   ├── mask_ops.py
│   │   ├── scale.py
│   │   ├── vectorize.py
│   │   ├── geometry.py         # jezičak, inset, kerf, validacije
│   │   ├── svg_writer.py
│   │   ├── slots.py            # PhotoSlot, LampTemplate, GeoJSON I/O
│   │   ├── decor.py            # DecorElement, izdvajanje (SAM klik, prag)
│   │   ├── compose.py          # popunjavanje slotova fotografijama, print sheet
│   │   ├── calibrate.py        # kalibracioni SVG + računanje kerfa
│   │   └── pipeline.py         # orkestracija + PipelineCache
│   ├── cli.py
│   └── ui/
│       ├── main_window.py
│       ├── canvas.py
│       ├── panels.py           # veličina, materijal, baza, kontura, elementi
│       └── workers.py          # QThreadPool/QRunnable
└── tests/
    ├── data/                   # uzorci + referentne maske
    └── test_*.py
```

### 4.2 Principi
- Svaka faza lanca vraća dataclass koji se može serijalizovati (debug, testovi).
- Debug režim (`--debug-dir`) snima međurezultate: sirova maska, očišćena maska, kontura preko slike, SVG preview.
- Težak model se učitava lenjo i samo jednom po procesu.
- Heširanje: za S1 **SHA256 bajtova fajla slike**, za ostale faze `frozen` dataclass-ovi (hashable); numpy nizovi se ne heširaju.

### 4.3 PipelineCache (faze i invalidacija)

| Faza | Zavisi od | Tipična cena |
|---|---|---|
| S1 embedding slike | slika (SHA256) | sekunde, jednom po slici |
| S2 maska | S1 + prompt (ili `mask_file`) | stotine ms |
| S3 čišćenje maske | S2 + parametri maske | desetine ms |
| S4 vektorizacija | S3 + skala | desetine ms |
| S5 geometrija (inset, jezičak, kerf) | S4 + baza + materijal + `kerf_mode` | ms |
| S6 izlazi (SVG, PNG) | S5 + slotovi + dekor | ms do sekunde |

Promena baze, kerfa, materijala ili veličine pokreće samo S4/S5-S6 (bez modela). Promena prompta pokreće S2 nadalje. `PipelineCache` je funkcija jezgra i testira se bez GUI-ja.

---

## 5. Modeli podataka (`models.py`, `slots.py`)

```python
@dataclass(frozen=True)
class Prompt:
    points: tuple[tuple[int, int], ...]      # (x, y) u pikselima originalne slike
    labels: tuple[int, ...]                  # 1 = pozitivna, 0 = negativna
    box: tuple[int, int, int, int] | None

@dataclass
class SegmentationResult:
    mask: np.ndarray               # bool, H x W, rezolucija originalne slike
    score: float
    all_candidates: list[np.ndarray]   # multimask kandidati (do 3)

@dataclass(frozen=True)
class ScaleInfo:
    mm_per_px: float
    reference: Literal["height", "width"]
    reference_mm: float              # odnosi se na izrezani deo BEZ jezička
    bbox_px: tuple[int, int, int, int]

@dataclass(frozen=True)
class MaterialProfile:
    id: str
    name: str
    thickness_mm: float
    kerf_mm: float
    min_feature_mm: float = 1.5
    notes: str = ""

@dataclass(frozen=True)
class BaseProfile:
    id: str
    name: str
    slot_length_mm: float            # dužina proreza u ravni ploče (izmerena ili nominalna)
    slot_thickness_mm: float         # širina proreza (po debljini akrila)
    slot_dimensions: Literal["measured", "nominal_laser_cut"] = "measured"
    base_kerf_mm: float = 0.0        # koristi se samo za "nominal_laser_cut"
    tab_width_mm: float = 0.0        # širina jezička u ravni ploče (nominalna, posle sečenja)
    tab_height_mm: float = 0.0       # dubina ulaska u prorez
    tab_fit_mm: float = 0.0          # ručna korekcija jezička (negativno = uže)
    tab_offset_mm: float = 0.0       # pomak jezička od sredine donjeg kontakta
    corner_radius_mm: float = 0.5

@dataclass
class CutGeometry:
    nominal: shapely.Polygon         # nominalni oblik dela + jezičak, u mm
    cut_path: shapely.Polygon        # putanja reza (posle kerf offseta)
    kerf_mm: float
    area_mm2: float
    bbox_nominal_mm: tuple[float, float, float, float]

@dataclass
class PhotoSlot:
    id: str
    polygon_mm: shapely.Polygon      # nominalna geometrija, koordinate lampe
    source: Literal["detected", "manual", "full_outline"]
    image_path: Path | None = None
    fit: Literal["cover", "contain"] = "cover"
    zoom: float = 1.0
    offset_mm: tuple[float, float] = (0.0, 0.0)
    rotation_deg: float = 0.0
    bleed_mm: float | None = None    # None = podrazumevano iz config-a

@dataclass
class DecorElement:
    id: str
    polygon_mm: shapely.Polygon | shapely.MultiPolygon
    source: Literal["sam_click", "threshold", "text"]
    mode: Literal["engrave", "print", "none"] = "engrave"
    engrave_style: Literal["fill", "line"] = "fill"
    color_override: str | None = None    # samo za štampu

@dataclass
class LampTemplate:
    outline: CutGeometry
    slots: list[PhotoSlot]
    decor: list[DecorElement]
    base: BaseProfile
    material: MaterialProfile
    scale: ScaleInfo
    input_kind: Literal["mockup", "photo"]
```

**Serijalizacija šablona (`.lamptpl`):** JSON; svi shapely objekti kao **GeoJSON**, koordinate zaokružene na 0,001 mm; uz verziju šeme (`"schema": 1`). `shapely.Polygon` se ne serijalizuje direktno.

---

## 6. Konfiguracija

### 6.1 Podrazumevane vrednosti (`config.py`)

| Parametar | Vrednost | Napomena |
|---|---|---|
| `sam_variant` | `auto` | prema 11.1; `tiny/small/base_plus/large` |
| `device` | `auto` | `cuda` → `mps` → `cpu` |
| `max_side_px` | 2048 | ne smanjuje VRAM enkodera (uvek 1024x1024) |
| `mask_min_component_frac` | 0.001 | |
| `mask_hole_min_area_mm2` | 4.0 | rupe se u v1 ionako popunjavaju |
| `mask_smooth_sigma_px` | 2.0 | |
| `potrace_turdsize` | 20 | |
| `potrace_alphamax` | 1.0 | |
| `potrace_opttolerance` | 0.2 | |
| `curve_sample_tol_mm` | 0.05 | |
| `kerf_mode` | `app` | ili `lightburn` |
| `edge_inset_mm` | 0.5 (mockup) / 0.8 (foto) | PROVIZORNO |
| `simplify_tol_mm` | 0.03 | |
| `engrave_margin_mm` | 1.5 | |
| `print_dpi` | 600 | DPI metapodatak i rezolucija izlaza |
| `print_bleed_mm` | 0.3 | 0.5 mm uz spoljnu ivicu konture; po slotu podesivo |
| `registration_marks` | `True` | |
| `svg_margin_mm` | 5.0 | |
| `cut_stroke` | `#FF0000`, 0.1 mm | |
| `engrave_color` | `#0000FF` | |

Konfiguracija se učitava iz `config.toml` (opciono); CLI argumenti je prepisuju.

### 6.2 Profili materijala (`materials.json`, korisnik ih menja u UI)

```json
[
  {"id": "acrylic-3", "name": "Akril providni 3 mm", "thickness_mm": 3.0, "kerf_mm": 0.18, "min_feature_mm": 1.5, "notes": ""},
  {"id": "acrylic-5", "name": "Akril providni 5 mm", "thickness_mm": 5.0, "kerf_mm": 0.22, "min_feature_mm": 2.0, "notes": ""}
]
```
(Vrednosti su ilustrativne; stvarne se određuju kalibracijom.)

### 6.3 Profili baze (`bases.json`, korisnik ih menja u UI)

```json
[
  {"id": "oval-wood", "name": "Ovalna drvena", "slot_length_mm": 80.0, "slot_thickness_mm": 3.4,
   "slot_dimensions": "measured", "base_kerf_mm": 0.0,
   "tab_width_mm": 78.0, "tab_height_mm": 8.0, "tab_fit_mm": 0.0, "tab_offset_mm": 0.0, "corner_radius_mm": 0.5}
]
```
(Ilustrativne vrednosti; korisnik unosi stvarne u UI.)

Svi profili (materijal, baza, uobičajene veličine lampe) čuvaju se u korisničkom folderu (`platformdirs`) kao JSON, sa uvozom/izvozom.

---

## 7. Specifikacija modula jezgra

### 7.1 `io_utils.py`
- `load_image(path) -> PIL.Image` (RGB, EXIF primenjen, upozorenje za malu rezoluciju).
- `file_sha256(path) -> str`.
- `save_png(img, path, dpi)` upisuje DPI metapodatak.
- `to_working_size(img, max_side)` i `mask_to_original(mask, factor, original_size)`.

### 7.2 `device.py`
- `pick_device()`: `cuda` → `mps` → `cpu`; moguće prepisati iz podešavanja.
- `pick_variant(device, vram_gb | ram_gb)`: tabela u 11.1.
- `load_with_fallback(...)`: pri `torch.cuda.OutOfMemoryError` oslobodi memoriju (`torch.cuda.empty_cache()`), spusti varijantu (`base_plus` → `small` → `tiny`), na kraju pređi na CPU, uz jasnu poruku korisniku.
- Na MPS: `PYTORCH_ENABLE_MPS_FALLBACK=1`, float32.

### 7.3 `segmentation.py`
Omotač oko SAM 2 (`sam2` paket, `SAM2ImagePredictor`). Nazive konfiguracija i checkpointa proveriti u instaliranoj verziji paketa.

```python
class Segmenter:
    def __init__(self, variant: str, device: str): ...
    def set_image(self, image: np.ndarray) -> None: ...      # embedding jednom po slici
    def predict(self, prompt: Prompt, multimask: bool = True) -> SegmentationResult: ...
```

Pravila:
- `set_image` jednom po slici; `predict` se poziva više puta (interaktivnost).
- Samo jedna tačka: `multimask_output=True`, bira se kandidat sa najvećim `score`-om; GUI nudi sva tri.
- Okvir (sa ili bez tačaka): `multimask_output=False`.
- Pomoćna funkcija `mask_from_file(path)` za `--mask-file` (binarna PNG maska iste rezolucije kao slika, ili automatski prilagođena).
- Opciono (faza 1+): automatski kandidati preko `SAM2AutomaticMaskGenerator` i heuristike (najveća maska koja ne dodiruje donju ivicu); uvek uz potvrdu korisnika.
- **Provera rezultata klika za slot:** posle `predict` za slot proveriti površinu (u razumnom opsegu), preklapanje sa već definisanim slotovima i kompaktnost (solidnost = površina / površina konveksnog omotača). Ako provera padne, ponuditi dodavanje negativnih tačaka ili ručni poligon.

### 7.4 `mask_ops.py`
Svaka operacija je zasebna funkcija koja se testira pojedinačno:

1. `largest_component(mask)` / `components(mask)` (v1: upozorenje ako ima više komponenti, vidi 8.3).
2. `fill_holes(mask)`: popunjava sve unutrašnje otvore (v1 seče samo spoljnu konturu).
3. `morph_close(mask, radius_px)`.
4. `smooth(mask, sigma)`: Gausovo zamućenje pa prag 0,5.
5. `refine_edge(image, mask, band_px)`: GrabCut ili guided filter u uskoj traci oko ivice (opciono, uključeno za `photo`).
6. `cut_at_line(mask, y_px)` / `remove_stand(mask, line)`: ravna donja ivica; korisnik povlači liniju "ovde počinje postolje" ili se uzima najniža ravna ivica.
7. `polygon_to_mask(points, shape)`: ručni poligon alat kao fallback.

### 7.5 `scale.py`
- `compute_scale(mask, reference, reference_mm) -> ScaleInfo`: `mm_per_px = reference_mm / bbox_dimension_px`; referenca je **izrezani deo bez jezička**; UI prikazuje i ukupnu visinu sa jezičkom.
- Upozorenje ako je odnos strana bbox-a neočekivan.
- Opciona kalibracija iz dve tačke sa poznatim razmakom (referentni objekat, npr. kartica 85,60 mm).

### 7.6 `vectorize.py`
Cilj: maska → zatvoren `shapely.Polygon` u mm.

1. Bitmapa za Potrace (uvećanje 2x sa bikubičnim glađenjem pri niskoj rezoluciji).
2. Potrace (`potracer`, čist Python; apstrakcija `PotraceBackend` radi lake zamene) daje putanje od linija i Bezijeovih krivih.
3. Adaptivno uzorkovanje Bezijeovih segmenata do `curve_sample_tol_mm`.
4. Množenje sa `mm_per_px` (uz korekciju uvećanja), y na dole.
5. Gradnja poligona; ako je nevalidan, `shapely.make_valid` pa izbor najvećeg poligona. Provera: bez samopreseka, jedna spoljna kontura.

Rezervni backend (ista apstrakcija): `cv2.findContours` + `cv2.approxPolyDP` + Čaikinovo glađenje.

### 7.7 `geometry.py`
Videti odeljak 8 (jezičak, inset, kerf, validacije). Sve funkcije rade nad `shapely` poligonima u mm.

### 7.8 `svg_writer.py`

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">
  <g id="cut-outer" fill="none" stroke="#FF0000" stroke-width="0.1">
    <path d="M x y L x y ... Z"/>
  </g>
  <g id="engrave" fill="#0000FF" stroke="#0000FF" stroke-width="0.1">
    <path d="..."/>
  </g>
</svg>
```

- **Koordinatni početak = gornji levi ugao NOMINALNE geometrije (pre kerf offseta) + `svg_margin_mm`.** Isti početak koriste `print_sheet.png` i `photo_XX.png` (odeljak 9.4). Putanja reza se zato translira prema bbox-u nominalne geometrije, a ne prema bbox-u nakon offseta.
- Koordinate zaokružene na 3 decimale; zatvorene putanje; bez `transform` atributa; bez teksta (sve u putanjama); jedna boja po sloju.
- Spoljna kontura i gravura u odvojenim grupama (slojevima).
- Validacija: ponovo učitati SVG i uporediti dimenzije sa očekivanim.
- **Test uvoza u LightBurn (ručno, korisnik):** kvadrat 100 x 100 mm mora imati tačno 100 mm u poljima "Size"; provera boje i sloja za gravuru. LightBurn uvoz ispuna/kontura zavisi od načina uvoza, pa je ovo obavezna provera u prihvatanju.

### 7.9 `calibrate.py`
`lampcutter calibrate --sizes 20,30,40` izvozi SVG sa kvadratima nominalnih dimenzija **bez** kerf kompenzacije. Posle sečenja korisnik meri kvadrate pomičnim merilom i unosi vrednosti; `kerf = nominalno - izmereno` (prosek) upisuje se u profil materijala. Isti postupak služi za proveru naleganja jezička u prorez.

### 7.10 `pipeline.py`
```python
def run_pipeline(image_path, prompt | mask_file, settings, material, base, out_dir,
                 progress=None, cancel=None) -> PipelineResult
```
Koristi `PipelineCache`. `progress(stage: str, fraction: float)`; prekid preko `cancel_token`.

---

## 8. Geometrija sečenja

### 8.1 Definicije
- **Nominalna geometrija:** oblik dela kakav treba da bude posle sečenja (uključujući jezičak).
- **Putanja reza:** za spoljnu konturu, nominalna geometrija pomerena **napolje** za `kerf/2`.

### 8.2 Redosled operacija (S5)
1. Poligon iz S4.
2. `edge_inset_mm`: `poly.buffer(-inset)` (kompenzacija sjaja), pa provera validnosti.
3. Popunjavanje otvora: `Polygon(poly.exterior)`.
4. Ravna donja ivica i **jezičak** (8.3), unija.
5. `simplify(simplify_tol_mm, preserve_topology=True)`.
6. Provera `min_feature_mm` (8.5).
7. Ako je `kerf_mode == "app"`: `cut_path = nominal.buffer(kerf/2, join_style="round", resolution=32)`; ako je `"lightburn"`: `cut_path = nominal`.

### 8.3 Jezičak i prorez baze (eksplicitna pravila)
Jezičak je pravougaonik širine `tab_width_mm`, visine `tab_height_mm`, sa zaobljenim uglovima, centriran na sredini donjeg kontakta plus `tab_offset_mm`; `tab_fit_mm` se primenjuje samo na jezičak (negativno = uže), pre unije sa telom.

- **Kerf i jezičak:** jezičak je deo spoljne konture i dobija isti offset od `kerf/2`, pa posle sečenja ima **tačno nominalnu** širinu `tab_width_mm`. Kerf se **ne** kompenzuje dodatno na jezičku.
- **Debljina akrila ulazi u prorez po debljini** (`slot_thickness_mm`); kerf tu ne učestvuje. Upozorenje ako je `material.thickness_mm > slot_thickness_mm`, ili ako je zazor po debljini veći od konfigurisanog praga.
- **Prorez u bazi:** ako baza nije lasersečena (`measured`), `slot_length_mm` je stvarna izmerena dužina. Ako jeste (`nominal_laser_cut`), efektivna dužina je `slot_length_mm + base_kerf_mm`.
- **Zazor u ravni:** `effective_slot_length - tab_width_mm`. UI ga prikazuje uživo i upozorava ako je negativan (neće ući) ili veći od 1,0 mm (klima).
- Validacija: jezičak ne sme biti širi od donjeg kontakta; rezultat je jedan validan poligon.

### 8.4 Višedelne konture
Posle čišćenja prebrojati komponente. Ako ih je više od jedne, ponuditi: (a) zadržati najveću, (b) dodati most minimalne širine, (c) otkazati. Spoljna kontura je uvek jedan poligon.

### 8.5 Kvalitet konture za laser
- Bez nazubljenja; bez veoma kratkih segmenata (< ~0,02 mm); zatvorena i bez samopreseka.
- Opciono zaobljavanje konkavnih uglova (`buffer(-r).buffer(r)`) zbog pucanja akrila u oštrim unutrašnjim uglovima.
- **Tanki delovi:** upozorenje ako postoji deo tanji od `min_feature_mm` (otvaranjem `buffer(-t/2).buffer(t/2)` i poređenjem površina); označiti mesto korisniku (npr. vratovi između glava).
- **`join_style="round"`** je namerno: putanja reza je zaobljena, ali ivica dela ostaje oštra na nominalnom mestu (spoljni uglovi dela se ne zaobljavaju). Konkavni uglovi dela ostaju sa radijusom oko `kerf/2`, što je fizičko ograničenje lasera. Dokumentovati u README-u.

### 8.6 Perspektiva (stvarne fotografije)
Pri `input_kind = photo`: upozorenje o frontalnom snimanju i ponuđena ručna korekcija (4 ugla poznatog pravougaonika ili referentni objekat) sa `cv2.warpPerspective` pre segmentacije.

---

## 9. Slotovi, dekor, šabloni i izlaz za štampu

### 9.1 Tok A: iz gotovog dizajna
1. **Slot:** korisnik klikne unutar fotografije (SAM 2 point prompt), maska se čisti, pretvara u poligon u mm i dodaje kao slot. Posebno dugme: "slot je cela kontura" (`full_outline`). Rezultat prolazi proveru iz 7.3.
2. **Dekor element:** dva načina izdvajanja:
   - **SAM klik:** krupni oblici (srca, ruža).
   - **Prag/boja u zoni:** korisnik povuče pravougaonik, podesi klizač praga (luminansa ili boja, adaptivni prag); rezultat ide kroz Potrace sa uvećanjem 2-3x. Tačnije za tanke linije i tekst, gde SAM često greši.
3. Isečak fotografije = originalni sadržaj slike unutar maske (RGBA). Aplikacija prijavljuje efektivni DPI i upozorava ispod 150 DPI.

### 9.2 Tok B: šablon + naknadne fotografije
1. Korisnik učitava `.lamptpl` (ili ga upravo napravi u Toku A, samo sa oblicima).
2. Za svaki slot bira fotografiju klijenta; podrazumevano `cover` (popuni i obreži), sa pomeranjem, zumiranjem i rotacijom u pregledu.
3. Izlaz je isti kao u Toku A, ali iz fotografija pune rezolucije.

### 9.3 Dekor: gravura ili štampa
| Režim | Gde ide |
|---|---|
| `engrave` | `lamp_cut.svg`, sloj `engrave`, boja `#0000FF`, **bez kerf offseta**. Vrsta obrade (Fill/Line) se bira po sloju u LightBurn-u. Opciono `engrave_bitmap.png` (grayscale). |
| `print` | `print_sheet.png` i `decor_XX.png`, isti koordinatni početak kao sečenje. |
| `none` | Ne izvozi se. |

Validacije: dekor mora biti unutar konture sa marginom (`outline.buffer(-engrave_margin_mm).contains(element)`); upozorenje za linije tanje od praga lasera/materijala.

**v1.1:** tekst kao objekat (korisnik ukucava tekst i bira font; `fontTools` → putanje), jer je čistiji od vektorizacije slike i omogućava promenu imena i datuma na šablonu.

### 9.4 Izlazi i poravnanje štampe i sečenja
- `lamp_cut.svg`, `print_sheet.png` i svi `photo_XX.png`/`decor_XX.png` dele **isti koordinatni početak** (gornji levi ugao nominalne geometrije + margina).
- **Štampa se računa nad nominalnom geometrijom, sečenje nad geometrijom sa kerfom.**
- `print_sheet.png`: cela lampa u razmeri 1:1 na `print_dpi`, slotovi na svojim pozicijama, providna pozadina, registracione oznake (podrazumevano uključene).
- `photo_XX.png`: RGBA, oblik slota kao alfa kanal, tačne dimenzije u mm x DPI, bleed (`print_bleed_mm`, 0,5 mm uz spoljnu ivicu konture, podesivo po slotu).
- Opcija redosleda: `cut_then_print` ili `print_then_cut` (uz LightBurn kameru); menja sadržaj print sheet-a (oznake, referentne tačke).
- Alternativa: "štampaj direktno na akril" (UV štampači koji to podržavaju) koristi `print_sheet.png` kao fajl za štampu; često je tačnije od naknadnog poravnanja.
- `manifest.json`: slotovi, poligoni u mm, efektivni DPI, korišćeni materijal i baza, verzija aplikacije.

---

## 10. CLI (Faza 0a i dalje)

```
lampcutter run slika.jpg \
    --point 820,540 --point 300,900:neg \
    --box 100,80,1500,1800 \
    [--mask-file maska.png] \
    --height-mm 250 --material acrylic-3 --base oval-wood \
    --input-kind mockup|photo --kerf-mode app|lightburn \
    --out ./izlaz --debug-dir ./izlaz/debug

lampcutter calibrate --sizes 20,30,40 --out ./kalibracija
lampcutter benchmark --images tests/data --out ./benchmark_report
```

Izlaz u `./izlaz`: `lamp_cut.svg`, `photo_*.png`, `decor_*.png`, `print_sheet.png`, `manifest.json`; u debug režimu i `mask_raw.png`, `mask_clean.png`, `overlay.png`, `contour_preview.svg`.

---

## 11. Hardver, modeli i rad bez interneta

### 11.1 Izbor modela
Enkoder SAM 2 uvek radi na 1024 x 1024; smanjenje `max_side_px` ne smanjuje VRAM. Varijanta zavisi od uređaja (PROVIZORNO do benchmarka):

| Uređaj | Podrazumevana | Dozvoljene | Napomena |
|---|---|---|---|
| RTX 3050 (4 GB) | `small` | `tiny`, `base_plus` (uz OOM lanac) | `large` isključen ispod ~8 GB; autocast bf16/fp16 |
| NVIDIA 6-8 GB | `base_plus` | do `large` | |
| NVIDIA 8 GB+ | `large` | sve | |
| Apple Silicon (MPS) | `base_plus` | `tiny`..`large` zavisno od RAM-a | fallback varijabla, float32, testirati rano |
| CPU | `tiny` ili `small` | | rezerva |

CUDA postoji samo na Windows/Linux; Mac koristi MPS. Pretpostavka: Mac za razvoj/rad, NVIDIA računar za brzu obradu.

### 11.2 Benchmark (`scripts/benchmark.py`)
Za svaku varijantu i uređaj meri: vreme `set_image`, vreme `predict`, vršnu potrošnju VRAM-a/RAM-a, odstupanje ivice (8.x metrika iz odeljka 13.2). **Rezultati određuju konačne podrazumevane vrednosti iz 11.1.** Dok benchmark nije izvršen, u `config.py` stoji `small` kao bezbedan izbor.

### 11.3 Offline pravila
- Checkpointi u `models/` (ili korisnički data folder) sa `manifest.json` i SHA256 proverom. Aplikacija ništa ne preuzima u radu.
- `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`; bez telemetrije i mrežnih poziva.
- Preuzimanje modela radi samo `scripts/fetch_models.py` (build-time).
- CI test blokira mrežu (`pytest-socket`) i proverava da ceo lanac radi.

---

## 12. GUI specifikacija (Faze 2-3)

### 12.1 Glavni prozor
- **Levo:** platno (`QGraphicsView`): slika, poluprozirna maska, kontura, tačke prompta, jezičak, slotovi, dekor. Zum točkićem, pomeranje srednjim tasterom.
- **Desno (paneli):**
  - **Veličina:** referentna strana (visina/širina), vrednost, jedinica (mm/cm), izračunata druga dimenzija i ukupna visina sa jezičkom; lista čestih veličina (S/M/L).
  - **Materijal:** padajuća lista, dugme "Uredi" (naziv, debljina, kerf, `min_feature_mm`), dupliranje/brisanje.
  - **Postolje:** padajuća lista i uređivač profila (dužina i debljina proreza, vrsta dimenzija, širina i visina jezička, zazor/fit, pomak, radijus); promena odmah crta jezičak i prikazuje zazor.
  - **Kontura:** vrsta ulaza, `edge_inset_mm`, `kerf_mode`, glatkoća.
  - **Elementi:** lista slotova i dekor elemenata sa režimom (gravura/štampa/ništa), fotografijom (Tok B) i pan/zoom pregledom.
- **Dole:** traka napretka, "Otkaži", "Izvezi".
- **Interakcija:** levi klik = pozitivna tačka, desni = negativna, prevlačenje = okvir. **Poligon alat** (klik-temena) kao fallback za maske (v1). "Poništi" briše poslednju radnju. Drag and drop učitava sliku.

### 12.2 Nitovi
- `QThreadPool` + `QRunnable` (ili `QThread` sa worker objektom) za: učitavanje modela, `set_image`, `predict`, izvoz.
- Signali: `progress(str, float)`, `finished(result)`, `failed(str)`.
- UI nit nikad ne dodiruje model; `predict` se debounce-uje (150 ms); zastareli zahtevi se odbacuju brojačem generacije.
- Model se učitava jednom pri pokretanju u pozadini ("Model se učitava...").

### 12.3 Projekat i stanje
Projekat `.lampproj` (JSON): putanja slike, prompt, podešavanja, reference na profile. Maska se ne čuva (preračunava se), osim ručnog poligona. Šablon `.lamptpl` (9.2, GeoJSON). Ručna četkica za retuš maske je v1.1.

### 12.4 Stil
QSS tema (svetla/tamna), jasne poruke na srpskom, i18n kroz `QTranslator`.

---

## 13. Testiranje i prihvatanje

### 13.1 Automatski testovi (`pytest`)

| Oblast | Test |
|---|---|
| `mask_ops` | Sintetičke maske sa šumom/rupama → očekivani rezultat |
| `scale` | Poznata maska + referenca → tačan `mm_per_px` |
| `geometry` kerf | Kvadrat 100x100 mm, kerf 0,2 → putanja 100,2 x 100,2 mm (tol. 0,01); nominalno 100x100 |
| `geometry` jezičak | Zadate dimenzije; jedan validan poligon; `tab_fit_mm` utiče samo na jezičak; posle offseta jezičak = nominalna širina |
| `geometry` zazor | Računanje zazora za `measured` i `nominal_laser_cut` |
| `vectorize` | Krug poznatog poluprečnika → odstupanje < 0,05 mm |
| `svg_writer` | Dimenzije SVG-a odgovaraju bbox-u; validan XML; slojevi i boje |
| Poravnanje | SVG i `print_sheet.png` renderovani preko istog početka poklapaju se u okviru **0,1 mm** (softverski, deterministično) |
| Slotovi | `cover` popunjava slot bez praznina; rotacija i zum daju očekivane izlaze; provera "pobeglog klika" |
| Dekor | `engrave` završava u sloju `#0000FF` bez kerfa; `print` samo u print sheet-u; margina |
| Serijalizacija | GeoJSON round-trip šablona (tol. 0,001 mm) |
| Višedelne konture | Maska sa dve komponente → upozorenje i akcija |
| Kalibracija | `kerf = nominalno - izmereno` na poznatim ulazima |
| Keš | Promena kerfa ne poziva S1-S4 (brojač poziva); promena prompta poziva S2 nadalje |
| OOM lanac | Simulirani OOM spušta varijantu i na kraju prelazi na CPU |
| Offline | Ceo lanac prolazi sa blokiranom mrežom |
| `pipeline` | End-to-end na 2-3 uzorka sa lažnom maskom (CI bez GPU-a) |

### 13.2 Metrika kvaliteta maske (PROVIZORNO)
IoU je slep za greške na ivici velikih objekata (za lampu od ~1000x1200 px IoU 0,97 dozvoljava više od 1 mm greške ivice). Zato je primarna metrika **u milimetrima**:

| Metrika | Mockup | Stvarna fotografija |
|---|---|---|
| Srednje odstupanje ivice | ≤ 0,2 mm | ≤ 0,3 mm |
| Hausdorff 95. percentil | ≤ 0,5 mm | ≤ 0,8 mm |

Brojeve potvrđuje/koriguje Faza E; IoU se prati samo dijagnostički. Obavezan je i vizuelni pregled preklopa konture preko slike pre izvoza.

### 13.3 Referentne maske
5-10 slika (uključujući stvarne fotografije upaljene lampe). Referentna maska: mašinski nacrt (SAM) pa ručna korekcija u uređivaču slika, sačuvana kao PNG u `tests/data/ref/`. **Ako slike ne postoje, agent traži od korisnika.**

### 13.4 Fizička prihvatanja (radi korisnik)
- Uvoz SVG-a u LightBurn daje tačne dimenzije (kvadrat 100 mm).
- Probni rez: ivice glatke; dimenzije delova u okviru tolerancije; jezičak ulazi u prorez bez prisile i bez zazora.
- **Fizičko poravnanje štampe:** realna tolerancija je oko 0,15 mm za lampe do 200 mm i oko 0,3 mm za veće (štampač, termička dilatacija, tolerancija reza); upisati u README i prikazati korisniku.
- Vreme obrade (cilj): < 15 s na CPU sa `small` modelom, < 3 s na GPU-u.

---

## 14. Pakovanje i distribucija
- Zavisnosti fiksirane u `pyproject.toml` + lock fajl (`uv`/`pip-tools`).
- Ciljne konfiguracije: **macOS arm64 (MPS)** i **Windows x64 sa CUDA PyTorch-om** (RTX 3050 je Ampere); opciono Linux CUDA.
- Alati: PyInstaller (Windows/Linux), PyInstaller ili `py2app` (macOS). Windows CUDA instalacija je velika (nekoliko GB); model pack se po želji isporučuje odvojeno.
- Istražiti ONNX Runtime izvoz enkodera/dekodera SAM 2 (rizik: ograničena podrška).
- Potpisivanje/notarizacija (macOS) i SmartScreen (Windows) planirati unapred.
- Testovi na čistim instalacijama macOS (Apple Silicon) i Windows 11.

---

## 15. Rizici

| Rizik | Verovatnoća | Mera |
|---|---|---|
| Segmentacija providnog/sjajnog akrila je netačna | Visoka | Faza E; negativne tačke; `edge_inset_mm`; `refine_edge`; `--mask-file` i poligon alat; klasični CV kao alternativa |
| Kriterijum IoU 0,97 nerealan na stvarnim fotografijama | Visoka | Metrika u mm (13.2) |
| Greška u naleganju jezička (kerf, prorez) | Srednja | Eksplicitna pravila 8.3, UI prikaz zazora, `calibrate`, probni rez |
| Poravnanje UV štampe | Visoka | Isti koordinatni početak, registracione oznake, štampa direktno na akril, dokumentovana fizička tolerancija |
| Potrace binding se ne pakuje | Srednja | `potracer` + OpenCV rezervni backend |
| SAM 2 prespor ili nedovoljno memorije (4 GB) | Srednja | `small`, OOM lanac, benchmark |
| MPS nepodržane operacije | Srednja | Fallback varijabla, rano testiranje |
| Kerf se razlikuje po mašini/materijalu | Visoka | Profili materijala + `calibrate` |
| Niska rezolucija isečaka za UV štampu | Visoka | Prikaz efektivnog DPI-a, Tok B |
| Veličina instalacije | Visoka | CPU/CUDA varijante, model pack, ONNX |
| "Pobegli" klik pri izdvajanju slotova | Srednja | Provera rezultata (7.3), negativne tačke, ručni poligon |

---

## 16. Plan rada (faze, kapije, definicija gotovog)

Redosled rada određuju stvarni rezultati (probni rezovi, fotografije), a ne kalendar.

### Faza E: Eksperiment sa sjajem (pre arhitekture)
**Cilj:** empirijski izabrati primarnu strategiju segmentacije i potvrditi realne pragove kvaliteta.
- Skript `experiments/glow_experiment.py` (izveštaj `experiments/REPORT.md` sa tabelom i preklopima).
- Ulaz: 3-5 slika, od toga **najmanje 2-3 stvarne fotografije upaljene lampe** i 2 mockupa; referentne maske (13.3); poznata stvarna visina za svaku (radi merenja u mm).
- Strategije: SAM 2 `small` sa tačkom, sa okvirom, sa tačkom+okvirom; GrabCut iz okvira; prag/Otsu u LAB prostoru.
- Merenje: srednje odstupanje ivice i Hausdorff95 u mm, uz IoU; test `edge_inset_mm` (0 / 0,5 / 1,0).
- **Kapija:** korisnik pregleda izveštaj i odobrava primarnu strategiju i pragove iz 13.2. Ako nijedna strategija ne dostiže pragove, pauza: revidirati pristup (npr. klasični CV kao primarni, uputstvo za fotografisanje).

### Faza 0a: Minimalni put do probnog reza
Obuhvata: `io_utils`, `segmentation` (tačka/okvir/`--mask-file`), osnovni `mask_ops`, `scale`, `vectorize`, kerf (bez jezička), `svg_writer`, CLI `run`, debug izlaz, minimalan offline loader. **Bez** jezička, profila materijala, keša i benchmarka.
- **DoD:** testovi prolaze; SVG kvadrat 100 mm uvezen u LightBurn je tačan; korisnik seče probni komad.
- **Kapija:** korisnik javlja izmerene dimenzije probnog reza (potvrda skale i kerfa).

### Faza 0b: Jezičak, materijali, kalibracija, keš, uređaji
Obuhvata: `BaseProfile` i jezičak (8.3), profili materijala i baza, `calibrate`, `PipelineCache`, `device.py` sa OOM lancem, kompletan `mask_ops` (komponente, popunjavanje otvora, `min_feature`), `benchmark`.
- **DoD:** testovi iz 13.1 za ove module; benchmark izveštaj za CUDA 4 GB i MPS; podrazumevane vrednosti 11.1 ažurirane iz benchmarka.
- **Kapija:** korisnik proverava naleganje jezička u stvarnu bazu probnim rezom.

### Faza 1: Slotovi, dekor, štampa
`PhotoSlot`/`LampTemplate`/`DecorElement`, GeoJSON I/O, Tok A i Tok B, režimi gravura/štampa, `print_sheet.png`, poravnanje, `manifest.json`.
- **DoD:** testovi poravnanja i dekora; uvoz gravure u LightBurn proveren.

### Faza 2: GUI kostur
Platno, nitovi, interaktivni prompt, poligon alat, lista slotova/elemenata.

### Faza 3: Podešavanja i projekti
Uređivači profila sa živim pregledom, `.lampproj`/`.lamptpl`, pan/zoom pregled fotografija, uvoz/izvoz profila.

### Faza 3b (v1.1)
Tekst kao objekat (fontovi), ručna četkica maske, automatsko centriranje na lica (lokalni detektor, offline).

### Faza 4: Dizajn i pakovanje
QSS, i18n, buildovi (macOS arm64, Windows CUDA), testovi na čistim instalacijama.

---

## 17. Provizorne vrednosti i otvorene stavke

**Provizorno (ne fiksirati bez potvrde):**
- `edge_inset_mm` (0,5 mockup / 0,8 foto), `refine_edge` širina trake.
- Pragovi kvaliteta u 13.2.
- Varijante modela po uređaju u 11.1 (do benchmarka).
- Vrednosti u primerima `materials.json` i `bases.json`.
- Prag zazora po debljini i u ravni (8.3).

**Zavisi od korisnika (podešava se u UI, ne traži se unapred):**
- Dimenzije proreza i jezička za svaku bazu, debljina akrila, kerf po materijalu, stvarna veličina lampe.

**Potrebno od korisnika za početak:**
- 2-3 stvarne fotografije upaljene lampe (ne mockup) + 2-3 mockupa sa poznatim visinama, za Fazu E i referentne maske.
