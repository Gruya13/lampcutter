# Poređenje platformi — SAM 2.1 benchmark

**Stanje:** CPU ✔ · CUDA (RTX 3050 Laptop) ✔ · **Apple Silicon MPS ⏳ (čeka se rezultat)**

Isti ulaz u sva tri slučaja: 3 sintetička mockupa (srce 200 mm, figura-8 220 mm,
ploča 150 mm) sa tačnim referentnim maskama. Detalji: [CPU](2026-11-03-cpu.md),
[CUDA](2026-11-03-cuda-rtx3050.md).

## Segmencija (srednje vrednosti preko 3 slike)

| metrika | CPU (16 jezgara) | CUDA (RTX 3050, 4 GB) | Apple Silicon MPS |
|---|---|---|---|
| torch verzija | 2.14.1+cpu | 2.14.1+cu130 | 2.14.1 (čeka se) |
| učitavanje modela (small) | 0.47 s | 0.49 s | — |
| `set_image` — tiny | 2.34 s | 0.26 s | — |
| `set_image` — small | 2.54 s | 0.03 s | — |
| `set_image` — base_plus | 4.27 s | 0.03 s | — |
| `set_image` — large | 10.74 s | 0.04 s | — |
| `predict` — tiny | 0.08 s | 0.07 s | — |
| `predict` — small | 0.07 s | 0.07 s | — |
| `predict` — base_plus | 0.08 s | 0.11 s | — |
| `predict` — large | 0.08 s | 0.25 s | — |
| memorija — large | 2163 MB RAM | 1451 MB VRAM | — |
| `large` staje u 4 GB? | da (CPU RAM) | **da** (1451 MB) | — |

## Kvalitet maske (srednje odstupanje ivice / HD95, mm)

Identifikovan isti redosled na CPU i CUDA; kvalitet zavisi od modela, ne od
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
| Apple Silicon | — | — | čeka se |

## Očekivanja za Apple Silicon (MPS) — hipoteza, ne nalaz

Mac je bolji za ML generalno, ali MPS nije isto što i CUDA:

1. **Unified memory je prednost** — nema 4 GB VRAM zida; `large` i veće slike će
   sigurno stati (dok ima RAM-a). Očekujemo da VRAM nikad ne bude problem.
2. **Brzina enkodera zavisi od čipa i broja GPU jezgara.** Očekivani opseg za
   `set_image` (small): ~0,05–0,3 s na M2/M3/M4; M1 može biti i sporiji.
   `predict` je sitan i biće sličan CPU/CUDA (0,1–0,3 s).
3. **MPS backend nije zreo kao CUDA.** Neke operacije nemaju MPS kernel pa idu na
   CPU fallback (`PYTORCH_ENABLE_MPS_FALLBACK=1`), što može da iskrivi merenje na
   gore. Zato je benchmark na Macu obavezan, a ne pretpostavka.
4. **Verzija sistema:** torch 2.14.1 macOS wheel zahteva **macOS 14+** (Sonoma).
   Na starijem macOS-u treba starija verzija torch-a — javiti tačnu grešku.
5. **Neural Engine se ne koristi** — PyTorch MPS koristi GPU, ne ANE; ne treba
   očekivati Apple-ove „ML brojeve" iz Core ML poređenja.

## Kad stigne Mac rezultat

1. Sačuvati kao `docs/benchmark/<datum>-mac-<čip>.md` + `.json` (npr.
   `2026-11-06-mac-m3-pro.md`), sa tačnim čipom i brojem GPU jezgara.
2. Dopuniti tabele u ovom dokumentu i u README-u.
3. Ažurirati podrazumevane varijante po uređaju (spec 11.1) i uporediti pragove
   13.2; odluka ide u Fazu 0b.
