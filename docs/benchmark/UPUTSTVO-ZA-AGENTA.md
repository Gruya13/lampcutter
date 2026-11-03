# Benchmark na ciljnoj mašini — uputstvo za agenta

**Cilj:** izmeriti SAM 2.1 varijante na ciljnom hardveru (Mac Apple Silicon sa MPS,
ili Windows/Linux sa NVIDIA GPU) i vratiti rezultate koji određuju podrazumevanu
varijantu modela po uređaju (specifikacija, 11.1) i pragove kvaliteta (13.2).

**Kome:** agent na drugarovoj mašini, sa pristupom ovom (privatnom) repozitorijumu.
Repozitorijum je privatan; pristup ide preko GitHub collaborator pozivnice.

**Šta ne treba raditi:** ne menjati `src/`, `tests/` ni `docs/api-phase0a.md`;
benchmark je samo merenje. Ako instalacija ne uspe, prijaviti tačnu grešku umesto
da se kod prilagođava.

---

## 1. Preuzmi repo

```bash
git clone https://github.com/Gruya13/lampcutter.git
cd lampcutter
```

Potreban je Python **3.12** i [uv](https://docs.astral.sh/uv/) (može i običan venv;
komande ispod koriste `uv`).

## 2. Instaliraj zavisnosti

```bash
uv sync --group dev
```

ML stack se instalira **van locka** (pinovane verzije; isti pinovi kao u CPU
benchmarku od 2026-11-03):

### macOS Apple Silicon (MPS)

> **Proveri prvo:** torch 2.14.1 macOS wheel zahteva **macOS 14 (Sonoma) ili noviji**.
> Zabeleži tačan čip i broj GPU jezgara (npr. `M3 Pro, 18 GPU jezgara`,
> `system_profiler SPHardwareDataType SPDisplaysDataType`) — to ide u izveštaj.

```bash
uv pip install torch==2.14.1 torchvision==0.29.1
uv pip install setuptools wheel hydra-core iopath tqdm
uv pip install --no-build-isolation "sam-2 @ git+https://github.com/facebookresearch/sam2.git@2b90b9f5ceec907a1c18123530e92e794ad901a4"
export PYTORCH_ENABLE_MPS_FALLBACK=1
```

### Windows / Linux + NVIDIA (CUDA)

Izaberi CUDA index prema drajveru; `cu128` odgovara Ampere generaciji (RTX 3050):

```bash
uv pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu128
uv pip install setuptools wheel hydra-core iopath tqdm
uv pip install --no-build-isolation "sam-2 @ git+https://github.com/facebookresearch/sam2.git@2b90b9f5ceec907a1c18123530e92e794ad901a4"
```

Provera da torch vidi uređaj:

```bash
uv run --no-sync python -c "import torch; print(torch.__version__, 'cuda=', torch.cuda.is_available(), 'mps=', getattr(torch.backends,'mps',None) and torch.backends.mps.is_available())"
```

## 3. Preuzmi checkpoint-e (~1.5 GB, jednom, build-time)

```bash
uv run --no-sync python scripts/fetch_models.py --variants tiny,small,base_plus,large
uv run --no-sync python scripts/fetch_models.py --verify
```

Ako je prostor/RAM ograničen, `large` (900 MB) može da se preskoči — dovoljno je
`--variants tiny,small,base_plus`.

## 4. Pokreni benchmark

```bash
uv run --no-sync python scripts/benchmark.py \
    --images tests/data \
    --variants tiny,small,base_plus,large \
    --reference-mm srce=200,figura8=220,ploca=150 \
    --out benchmark_report
```

- Uređaj se detektuje automatski (`cuda` → `mps` → `cpu`); može se forsirati sa
  `--device cuda|mps|cpu`.
- Očekivano trajanje: CPU ~5 min; na GPU/MPS znatno kraće. `large` na CPU/Mac-u
  može da traje nekoliko minuta i traži ~2,2 GB RAM samo za model — u redu je
  preskočiti `large` ako mašina nema dovoljno memorije.
- Skripta ne pada ako jedna varijanta ne uspe (OOM i sl.): greška se upiše u izveštaj.

## 5. Šta vratiti

Dva fajla iz `benchmark_report/`:

1. `BENCHMARK.md` — tabela sa vremenima i odstupanjem ivice,
2. `benchmark.json` — sirovi podaci (uključuju tačan model mašine, torch verziju,
   CUDA/MPS status, RAM/VRAM).

Ako je moguće, pošalji i prvih ~30 linija `benchmark.json` (sekcija `environment`).

**Bonus — materijal za Fazu E (dostavlja Dalibor):** ako Dalibor ima pristup
gotovim lampama, zajedno sa benchmarkom prikupite i pošaljite **2–3 fotografije
upaljene lampe** i **2–3 mockupa sa poznatim stvarnim visinama** (detalji i
tabela: `docs/VERIFIKACIJA.md`, sekcija 4). To je ulaz za eksperiment
segmentacije na stvarnim slikama.
Rezultati će biti upoređeni sa CPU rezultatima u
[`2026-11-03-cpu.md`](2026-11-03-cpu.md), a zatim commitovani u
`docs/benchmark/<datum>-<platforma>.md`.

## 6. Napomene

- `tests/data` sadrži **3 sintetička mockupa** (srce 200 mm, figura-8 220 mm, ploča
  150 mm) sa tačnim referentnim maskama u `tests/data/ref/`. Ne menjati ih — ista
  tri uzorka su korišćena u CPU benchmarku, pa su rezultati uporedivi.
- Ovo su sintetički uzorci: vremena su relevantna, a kvalitet maske je samo
  indikativan — stvarne fotografije upaljene lampe dolaze u Fazi E (spec 13.3),
  a prikuplja ih i dostavlja Dalibor (vidi `docs/VERIFIKACIJA.md` §4).
- Za Mac: ako MPS ne podržava neku operaciju, `PYTORCH_ENABLE_MPS_FALLBACK=1` je
  već postavljen u koracima iznad; upozorenje o fallback-u je očekivano i utiče na
  brzinu — navedi ga u izveštaju ako se pojavi često.
- Na Macu se ne koristi Neural Engine — PyTorch MPS koristi samo GPU.
- Modeli se **ne commit-uju** (`.gitignore`), samo `models/manifest.json` sa SHA256.
- `uv run` bez `--no-sync` bi uklonio ML pakete iz okruženja (nisu u locku) — zato
  je svuda naveden `--no-sync`.

## Troubleshooting

| Simptom | Rešenje |
|---|---|
| `torch is not installed` | koraci iz sekcije 2 |
| `SAM 2 is not installed` | `uv pip install --no-build-isolation "sam-2 @ git+...@2b90b9f5"` |
| `Missing checkpoint` | `uv run --no-sync python scripts/fetch_models.py ...` |
| `SHA256 mismatch` | obrisati fajl u `models/` i ponovo preuzeti |
| CUDA OOM kod `large` | pokrenuti bez `large` varijante |
| MPS greška o nepodržanoj operaciji | proveriti da je `PYTORCH_ENABLE_MPS_FALLBACK=1` postavljen |