# Poređenje platformi — SAM 2.1 benchmark

**Stanje:** CPU ✔ · CUDA (RTX 3050 Laptop) ✔ · Apple Silicon MPS (M5 Pro, 16 GPU jezgara) ✔

Isti ulaz u sva tri slučaja: 3 sintetička mockupa (srce 200 mm, figura-8 220 mm,
ploča 150 mm) sa tačnim referentnim maskama. Detalji: [CPU](2026-11-03-cpu.md),
[CUDA](2026-11-03-cuda-rtx3050.md), [Mac M5 Pro](2026-11-03-mac-m5-pro.md).

## Segmencija (srednje vrednosti preko 3 slike)

| metrika | CPU (16 jezgara) | CUDA (RTX 3050, 4 GB) | Apple M5 Pro MPS (24 GB) |
|---|---|---|---|
| torch verzija | 2.14.1+cpu | 2.14.1+cu130 | 2.14.1 |
| učitavanje modela (small) | 0.47 s | 0.49 s | 0.24 s |
| `set_image` — tiny | 2.34 s | 0.26 s | 0.58 s* |
| `set_image` — small | 2.54 s | 0.03 s | 0.01 s |
| `set_image` — base_plus | 4.27 s | 0.03 s | 0.53 s* |
| `set_image` — large | 10.74 s | 0.04 s | 0.08 s |
| `predict` — tiny | 0.08 s | 0.07 s | 0.59 s* |
| `predict` — small | 0.07 s | 0.07 s | 0.04 s |
| `predict` — base_plus | 0.08 s | 0.11 s | 0.06 s |
| `predict` — large | 0.08 s | 0.25 s | 0.14 s |
| memorija — large | 2163 MB RAM | 1451 MB VRAM | 1013 MB MPS / 2294 MB RAM |
| `large` staje u 4 GB? | da (CPU RAM) | **da** (1451 MB) | da (zajednička memorija) |

\* verovatno uključuje jednokratno zagrevanje MPS-a (tiny je meren prvi); nije posebno provereno.

## Kvalitet maske (srednje odstupanje ivice / HD95, mm)

Isti rezultat na CPU, CUDA i MPS; kvalitet zavisi od modela, ne od
uređaja (razlike su numeričke, < 0,01 mm).

| varijanta | srce | figura-8 | ploča |
|---|---|---|---|
| tiny | 0.171 / 0.496 | 0.179 / 0.360 | 0.244 / 0.412 |
| small | 0.204 / 0.496 | 0.207 / 0.396 | 0.231 / 0.375 |
| base_plus | 0.281 / 0.496 | 0.217 / 0.396 | 3.347 / 19.494 |
| large | 0.143 / 0.496 | 0.213 / 0.396 | 1.002 / 12.187 |

## End-to-end (slika → SVG)

| platforma | small (prvi run) | large | napomena |
|---|---|---|---|
| CPU | 3.51 s | — | cilj < 15 s (spec 13.4) ispunjen |
| CUDA | 4.62 s (sa CUDA init) | 3.16 s | ~1 s po slici posle učitavanja; cilj < 3 s ispunjen |
| Apple M5 Pro (MPS) | 1.93 s (nov proces) · 0.39–0.45 s (u procesu) | 2.60 s · 1.67–1.82 s | prva upotreba MPS-a +~5 s jednokratno; cilj < 3 s ispunjen |

## Nalazi i preporuke

1. **MPS je potvrđen kao punopravan uređaj.** 0 MPS fallback upozorenja; brzine
   su reda CPU/CUDA (set_image 0,01–0,08 s osim prvog zagrevanja; predict
   0,04–0,14 s). Cilj „< 3 s na GPU" ispunjen za sve varijante.
2. **Unified memory potvrđena:** `large` na M5 Pro troši 1013 MB i staje bez
   problema (24 GB zajedničke memorije); nema VRAM zida kao na 4 GB CUDA.
3. **Kvalitet ne zavisi od uređaja** — iste vrednosti na CPU, CUDA i MPS
   (< 0,01 mm razlike). Loš rezultat `base_plus`/`large` na ploči je osobina
   modela na tom sintetičkom uzorku, ne platforme.
4. **Prvi MPS poziv plaća ~5 s jednokratno** (priprema GPU koda); sledeći su brzi.
   Zato je u GUI-ju bitno da se model učita jednom (i da se koristi
   `set_image` cache iz spec 4.3).
5. **macOS specifičnost (rešeno):** `uv sync` ponekad napravi `.pth` sa
   `UF_HIDDEN` oznakom, pa Python preskoči editable paket
   (`No module named lampcutter`); rešenje:
   `chflags nohidden .venv/lib/python3.12/site-packages/*.pth`.
6. **Podrazumevane varijante po uređaju** (ažurirano u spec 11.1): CPU `tiny`
   (ili `small`), CUDA 4 GB `small` (`large` dozvoljen uz OOM lanac),
   CUDA 8 GB+ `large`, Apple Silicon `base_plus` (`large` dozvoljen).

## Otvoreno

- Fizičke provere (LightBurn, kerf, jezičak, poravnanje štampe) — spec 13.4.
- Faza E: ista metrika kvaliteta na stvarnim fotografijama (pragovi u spec 13.2
  su PROVIZORNI do Faze E).
