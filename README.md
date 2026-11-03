# Lampcutter

Desktop aplikacija koja od slike dizajna akrilne lampe pravi:

- `lamp_cut.svg` — konturu za lasersko sečenje u milimetrima (za LightBurn),
- `photo_*.png` i `print_sheet.png` — fajlove za UV štampu,
- opcioni sloj gravure (`#0000FF`) u istom SVG-u.

Specifikacija je jedini izvor istine: [LAMPCUTTER_SPEC.md](LAMPCUTTER_SPEC.md).

## Status

Verzija **0.5.0**. Sve glavne faze su završene:

- **geometrija** — učitavanje slike, maska (SAM 2 tačka/okvir, `--mask-file` ili
  ručni poligon), čišćenje maske, skala u mm, vektorizacija, edge inset, kerf
  kompenzacija, jezičak i prorez baze, SVG za LightBurn i debug izlazi;
- **slotovi, dekor i štampa** — slotovi za fotografije proizvoljnog oblika,
  režimi `engrave`/`print`/`none`, `print_sheet.png` 1:1 sa registracionim
  oznakama, `photo_XX.png`/`decor_XX.png`, `manifest.json`;
- **GUI** — platno sa interaktivnim promptom i poligonom, paneli, pozadinski
  izvoz, projekti (`.lampproj`), šabloni (`.lamptpl`), uređivači profila i
  ručna četkica za retuš maske;
- **distribucija** — samostalni paketi za Linux, macOS i Windows.

Preuzimanje: [Releases](https://github.com/Gruya13/lampcutter/releases).

**Faza E** (eksperiment segmentacije na stvarnim fotografijama) čeka ulazni
materijal: 2–3 fotografije upaljene lampe i 2–3 mockupa sa poznatim visinama.

## Instalacija

Preuzmi arhivu za svoj sistem sa [Releases](https://github.com/Gruya13/lampcutter/releases)
i raspakuj — detalji, macOS Gatekeeper i sistemske biblioteke:
[docs/INSTALACIJA.md](docs/INSTALACIJA.md).

Iz izvora (razvoj):

```bash
git clone https://github.com/Gruya13/lampcutter.git
cd lampcutter
uv sync --group dev --extra gui
```

Ciljna Python verzija je 3.12 (zbog PyTorch/SAM 2).

## Korišćenje

### CLI

```bash
# bez modela: gotova maska + poznata visina dela u mm
uv run lampcutter run slika.jpg --mask-file maska.png --height-mm 250 \
    --material acrylic-3 --out izlaz --debug-dir izlaz/debug

# sa SAM 2 modelom (kad su checkpointi u models/ i ML zavisnosti instalirane)
uv run lampcutter run slika.jpg --point 820,540 --point 300,900:neg \
    --height-mm 250 --material acrylic-3 --out izlaz

# kalibracija kerfa (kvadrati 100/20/30/40 mm)
uv run lampcutter calibrate --sizes 100,20,30,40 --out proba/kalibracija

# izvoz štampe i gravure iz šablona
uv run lampcutter export --template sablon.lamptpl --out izlaz --print-dpi 300
```

Izlaz: `lamp_cut.svg` (mm, cut sloj `#FF0000`, gravura `#0000FF`), debug
(`mask_raw.png`, `mask_clean.png`, `overlay.png`, `contour_preview.svg`) i,
za šablone, `print_sheet.png`, `photo_XX.png`, `manifest.json`.
`--base` dodaje jezičak i ispisuje zazor prema profilu baze.

### GUI

```bash
uv run --no-sync lampcutter gui [slika.png]   # tamna tema (--theme light za svetlu)
```

Platno sa promptom (levi klik pozitivna, desni negativna tačka, prevlačenje
okvir), poligon alat, paneli (Veličina, Materijal, Postolje, Kontura, Četkica,
Elementi), projekti, šabloni i četkica za retuš maske.

## Razvoj

```bash
uv sync --group dev --extra gui   # okruženje sa GUI zavisnostima
uv run ruff check .               # lint
./scripts/ci.sh                   # lint + svi testovi (GUI testovi offscreen)
```

## Benchmark

ML stack (torch + SAM 2) se instalira van locka — `uv sync` ga uklanja:

```bash
uv pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
uv pip install setuptools wheel hydra-core iopath tqdm
uv pip install --no-build-isolation "sam-2 @ git+https://github.com/facebookresearch/sam2.git@2b90b9f5ceec907a1c18123530e92e794ad901a4"
uv run --no-sync python scripts/fetch_models.py --variants tiny,small,base_plus,large
uv run --no-sync python scripts/benchmark.py --images tests/data --variants tiny,small,base_plus,large \
    --reference-mm srce=200,figura8=220,ploca=150 --out benchmark_report
```

Rezultati:

- **CUDA (RTX 3050 Laptop, 4 GB)** — [2026-11-03-cuda-rtx3050.md](docs/benchmark/2026-11-03-cuda-rtx3050.md):
  `set_image` 0,03 s (~85× brže od CPU), `large` staje u 4 GB VRAM.
- **CPU (16 jezgara)** — [2026-11-03-cpu.md](docs/benchmark/2026-11-03-cpu.md):
  `small` je najbolji balans — **3,5 s end-to-end**, ispod cilja od 15 s.
- **macOS (MPS)** — još se meri; uporedna tabela:
  [docs/benchmark/POREDJENJE-PLATFORMI.md](docs/benchmark/POREDJENJE-PLATFORMI.md).

Uputstvo za pokretanje benchmarka na drugoj mašini:
[docs/benchmark/UPUTSTVO-ZA-AGENTA.md](docs/benchmark/UPUTSTVO-ZA-AGENTA.md).

## Distribucija

```bash
uv run python scripts/build.py --archive   # dist/lampcutter-<verzija>-<platforma>.zip
```

Na tag `v*` se automatski prave paketi za Linux, macOS i Windows i kače na
GitHub Release. Uputstvo za korisnike: [docs/INSTALACIJA.md](docs/INSTALACIJA.md).

## Verifikacija

Šta proveriti i dostaviti pre izdavanja — benchmark, fizičke probe po fazama
(LightBurn dimenzije, kerf, jezičak, gravura, poravnanje štampe) i ulazni
materijal za Fazu E: [docs/VERIFIKACIJA.md](docs/VERIFIKACIJA.md).

## Struktura

```
src/lampcutter/   jezgro (bez Qt zavisnosti) + CLI + GUI
tests/            testovi i uzorci (data/ = slike i referentne maske)
scripts/          benchmark, preuzimanje modela, build, CI
models/           checkpointi + manifest.json (SHA256)
docs/             instalacija, verifikacija, API i benchmark
resources/        prevodi (i18n)
experiments/      Faza E: glow_experiment.py
```
