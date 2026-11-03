# Lampcutter

Desktop aplikacija koja od slike dizajna akrilne lampe pravi:

- `lamp_cut.svg` — konturu za lasersko sečenje u milimetrima (za LightBurn),
- `photo_*.png` i `print_sheet.png` — fajlove za UV štampu,
- opcioni sloj gravure (`#0000FF`) u istom SVG-u.

Specifikacija je jedini izvor istine: [LAMPCUTTER_SPEC.md](LAMPCUTTER_SPEC.md).

## Status

**Faza 0a (završena):** geometrijski lanac radi end-to-end — učitavanje slike,
maska (`--mask-file`, SAM 2 tačka/okvir ili ručni poligon), čišćenje maske,
skala u mm, vektorizacija, edge inset, kerf kompenzacija, SVG za LightBurn i
debug izlazi.

**v1.1 — ručna četkica (završena):** retuš maske posle segmentacije —
okrugla četkica (levi taster dodaje, desni uklanja), panel sa veličinom i
režimom, ponovna vektorizacija iz retuširane maske bez modela
(`revectorize_mask`), istorija poteza (10) sa `Poništi`. Test set četkice: 36
testova.

**Faza 4 (završena):** verzija `0.4.0` (`--version`), samostalni
PyInstaller paketi za Linux/macOS/Windows (`scripts/build.py --archive`),
release workflow na tag `v*`, instalacijsko uputstvo
[docs/INSTALACIJA.md](docs/INSTALACIJA.md), `fetch-depth: 0` u CI-ju (lock
proverava git revizije). Test set Faze 4: 30 testova.

**Faza 3 (završena):** projekti `.lampproj` (putanja slike, prompt/poligon,
veličina, profili, kerf — reprodukuju isti izlaz), uređivači profila materijala i
postolja sa upisom u korisnički folder (izmena kerfa važi za sledeći izvoz),
čuvanje/otvaranje `.lamptpl` šablona kroz UI, dodavanje slotova/dekora iz
poligona i izmena režima, i18n hook (`QTranslator`). Test set Faze 3: 41 test.

**Faza 2 (završena):** GUI kostur u PySide6 — `QGraphicsView` platno (slika,
maska, kontura, slotovi, dekor), zum točkićem i pan srednjim tasterom, interaktivni
prompt (levi klik pozitivna, desni negativna tačka, prevlačenje okvir), poligon
alat, paneli (Veličina, Materijal, Postolje, Kontura, Elementi), pozadinski
	extit{workers} sa generacijama za odbacivanje zastarelih rezultata i debounce
predikcije. Pokretanje: `lampcutter gui [slika]`. Test set Faze 2: 37 testova
(offscreen).

**Faza 1 (završena):** slotovi za fotografije proizvoljnog oblika (`PhotoSlot`),
dekor (`DecorElement`, izdvajanje pragom/bojom u zoni ili SAM maskom), režimi
`engrave`/`print`/`none`, `print_sheet.png` 1:1 sa registracionim oznakama,
`photo_XX.png`/`decor_XX.png`, `.lamptpl` GeoJSON šabloni (round-trip 0,001 mm)
i `manifest.json`. Poravnanje štampe i sečenja kroz zajednički koordinatni
početak. Test set Faze 1: 42 testa.

**Faza 0b (završena):** jezičak i prorez baze (spec 8.3) sa zazorom i
upozorenjima, kalibracija kerfa (`lampcutter calibrate`), `PipelineCache` (faze
S1–S6), `refine_edge` za stvarne fotografije i benchmark (CPU + CUDA; Mac MPS se
čeka). Zaključani test setovi: Faza 0a 38, Faza 0b 37, Faza 1 42, Faza 2 37,
Faza 3 41, Faza 4 30, četkica 36 — ukupno 261 test, svi prolaze. Fizička provera (LightBurn uvoz, probni rez, naleganje jezička) je na
korisniku kad bude imao vremena.

**Faza E (odložena):** čeka 2–3 stvarne fotografije upaljene lampe i 2–3 mockupa
sa poznatim visinama (specifikacija, 13.3 i 17). Do tada se ne piše
`segmentation`-zavisan kod iznad onoga što već postoji.

Radi se po fazama iz specifikacije, odeljak 16; korisnik je odobrio da Faza 0a
ide pre Faze E dok ne stignu fotografije.

## Razvoj

```bash
uv sync --group dev        # razvojno okruženje
uv run ruff check .        # lint
./scripts/ci.sh            # lint + zaključani test set (kao na CI-ju)
uv run python scripts/run_cases.py tests/cases/phase0a.json   # test set 0a
uv run python scripts/run_cases.py tests/cases/phase0b.json   # test set 0b
uv run python scripts/run_cases.py tests/cases/phase1.json    # test set 1
QT_QPA_PLATFORM=offscreen uv run python scripts/run_cases.py tests/cases/phase2.json  # test set 2 (GUI)
uv run python scripts/run_cases.py tests/cases/phase3.json    # test set 3
uv run python scripts/run_cases.py tests/cases/phase4.json    # test set 4 (distribucija)
QT_QPA_PLATFORM=offscreen uv run python scripts/run_cases.py tests/cases/brush.json  # v1.1 četkica
```

Ciljna Python verzija je 3.12 (zbog PyTorch/SAM 2).

## Korišćenje (Faza 0a)

```bash
# bez modela: gotova maska + poznata visina dela u mm
uv run lampcutter run slika.jpg --mask-file maska.png --height-mm 250 \
    --material acrylic-3 --out izlaz --debug-dir izlaz/debug

# sa SAM 2 modelom (kad su checkpointi u models/ i ML zavisnosti instalirane)
uv run lampcutter run slika.jpg --point 820,540 --point 300,900:neg \
    --height-mm 250 --material acrylic-3 --out izlaz
```

Izlaz: `lamp_cut.svg` (mm, sloj `cut-outer` u `#FF0000`). Debug:
`mask_raw.png`, `mask_clean.png`, `overlay.png`, `contour_preview.svg`.
`--base` dodaje jezičak i ispisuje zazor prema profilu baze.

## GUI

```bash
uv pip install PySide6==6.12.0               # GUI zavisnost (nije u locku)
uv run --no-sync lampcutter gui [slika.png]   # tamna tema (--theme light za svetlu)
```

GUI: platno sa interaktivnim promptom i poligonom, paneli, pozadinski izvoz,
uređivači profila, čuvanje/otvaranje projekata (`.lampproj`) i šablona
(`.lamptpl`), dodavanje slotova/dekora iz poligona i **ručna četkica za retuš
maske** (v1.1).

## Distribucija

```bash
uv run python scripts/build.py --archive   # dist/lampcutter-<verzija>-<platforma>.zip
```

Release workflow na tag `v*` pravi pakete za Linux, macOS i Windows.
Uputstvo za korisnike: [docs/INSTALACIJA.md](docs/INSTALACIJA.md).

## Verifikacija (za Dalibora i agente)

Kompletno uputstvo šta proveriti i dostaviti — benchmark na Mac-u, fizičke probe
po fazama (LightBurn dimenzije, kerf, jezičak, gravura, poravnanje štampe) i
ulazni materijal za Fazu E:
[docs/VERIFIKACIJA.md](docs/VERIFIKACIJA.md).

## Benchmark

Instalacija ML stacka van locka (CPU wheel; `uv sync` bi ga uklonio):

```bash
uv pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
uv pip install setuptools wheel hydra-core iopath tqdm
uv pip install --no-build-isolation "sam-2 @ git+https://github.com/facebookresearch/sam2.git@2b90b9f5ceec907a1c18123530e92e794ad901a4"
uv run --no-sync python scripts/fetch_models.py --variants tiny,small,base_plus,large
uv run --no-sync python scripts/benchmark.py --images tests/data --variants tiny,small,base_plus,large \
    --reference-mm srce=200,figura8=220,ploca=150 --out benchmark_report
```

Uputstvo za pokretanje na drugoj mašini (Mac MPS / CUDA, za collaboratora):
[docs/benchmark/UPUTSTVO-ZA-AGENTA.md](docs/benchmark/UPUTSTVO-ZA-AGENTA.md).

Uporedna tabela svih platformi (Mac MPS se čeka):
[docs/benchmark/POREDJENJE-PLATFORMI.md](docs/benchmark/POREDJENJE-PLATFORMI.md).

Rezultati (sintetički mockupi, isti uzorci za obe platforme):

- **CUDA (RTX 3050 Laptop, 4 GB)** — [2026-11-03-cuda-rtx3050.md](docs/benchmark/2026-11-03-cuda-rtx3050.md):
  `set_image` 0,03 s (**~85× brže od CPU**), `large` staje u 4 GB VRAM (1451 MB),
  end-to-end ~1 s po slici posle učitavanja modela.
- **CPU (16 jezgara)** — [2026-11-03-cpu.md](docs/benchmark/2026-11-03-cpu.md):
`small` je najbolji balans — set_image 2,5 s, predict 0,07 s, **3,5 s end-to-end**,
ispod cilja od 15 s iz spec 13.4. Na CUDA 4 GB i Mac MPS benchmark se još pokreće
(skripta detektuje uređaj automatski).

## Testovi i zaključavanje

Testove piše **agy** iz specifikacije i API ugovora (`docs/api-phase0a.md`), a
DSH ih preuzima i izvršava — ne menja ih. Test set je `tests/cases/*.json`
(sadrži pytest izvorni kod), zaključan kroz `agent-probe/test-lock.mjs`.

```bash
node agent-probe/test-lock.mjs check tests/cases/phase0a.json --require-git
uv run python scripts/run_cases.py tests/cases/phase0a.json
```

`.wiki/` je embedded git repo (dokaz autorstva i lock kopije); ne ulazi u glavni
repo.

## Struktura

```
src/lampcutter/   jezgro (bez Qt zavisnosti) + CLI + GUI
tests/            pytest testovi (data/ = uzorci i referentne maske)
experiments/      Faza E: glow_experiment.py
scripts/          benchmark, fetch_models, ci
models/           checkpointi + manifest.json (SHA256)
docs/             API ugovor za test set (docs/api-phase0a.md)
agent-probe/      test-lock alat (integritet test seta)
wiki/             wiki MCP server (dokazni kanal)
```