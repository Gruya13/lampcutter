# Lampcutter

Desktop aplikacija koja od slike dizajna akrilne lampe pravi:

- `lamp_cut.svg` — konturu za lasersko sečenje u milimetrima (za LightBurn),
- `photo_*.png` i `print_sheet.png` — fajlove za UV štampu,
- opcioni sloj gravure (`#0000FF`) u istom SVG-u.

Specifikacija je jedini izvor istine: [LAMPCUTTER_SPEC.md](LAMPCUTTER_SPEC.md).

## Status

**Faza 0a (u toku):** geometrijski lanac radi end-to-end — učitavanje slike,
maska (`--mask-file`, SAM 2 tačka/okvir ili ručni poligon), čišćenje maske,
skala u mm, vektorizacija, edge inset, kerf kompenzacija, SVG za LightBurn i
debug izlazi. Bez jezička, profila baze, keša i benchmarka (Faza 0b).

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
uv run python scripts/run_cases.py tests/cases/phase0a.json   # test set
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
`--base` se prihvata i ignoriše do Faze 0b (jezičak).

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