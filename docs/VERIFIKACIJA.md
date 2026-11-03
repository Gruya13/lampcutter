# Verifikacija Lampcutter-a — uputstvo za Dalibora i njegove agente

Ovo uputstvo opisuje **šta tačno treba proveriti i dostaviti** posle Faza 0a, 0b
i 1, plus benchmark na Mac-u i ulazni materijal za Fazu E.

## 0. Podela rada

| Ko | Šta radi |
|---|---|
| **Agenti** | kloniraju repo, instaliraju zavisnosti, generišu fajlove, pokreću benchmark, popunjavaju tabele, otvaraju PR |
| **Dalibor** | fizičke radnje: uvoz u LightBurn, sečenje, merenje pomičnim merilom, štampa, fotografisanje |
| **DSH + Agi** | implementacija, testovi, obrada nalaza |

Repo je **privatan**: sve što se pošalje (fotografije klijenata, probni rezovi)
ostaje u privatnom repou. Ne objavljivati javno.

## 1. Pristup i priprema

1. Prihvati GitHub collaborator pozivnicu (write) — bez toga repo nije vidljiv.
2. Kloniraj i pripremi okruženje:

```bash
git clone https://github.com/Gruya13/lampcutter.git
cd lampcutter
uv sync --group dev
```

Potrebno: Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js (za proveru
zaključanih testova). Za fizičke provere: laser (LightBurn) i pomični merilo.

> Sve komande ispod pokreći iz korena repoa. Rezultate piši u folder `proba/`
> (nije u .gitignore — može u PR).

## 2. Benchmark na Mac Silicon (MPS)

Detaljno u [docs/benchmark/UPUTSTVO-ZA-AGENTA.md](benchmark/UPUTSTVO-ZA-AGENTA.md);
kratko:

```bash
# macOS Apple Silicon; torch 2.14.1 zahteva macOS 14+
uv pip install torch==2.14.1 torchvision==0.29.1
uv pip install setuptools wheel hydra-core iopath tqdm
uv pip install --no-build-isolation "sam-2 @ git+https://github.com/facebookresearch/sam2.git@2b90b9f5ceec907a1c18123530e92e794ad901a4"
export PYTORCH_ENABLE_MPS_FALLBACK=1

uv run --no-sync python scripts/fetch_models.py --variants tiny,small,base_plus,large
uv run --no-sync python scripts/fetch_models.py --verify
uv run --no-sync python scripts/benchmark.py --images tests/data \
    --variants tiny,small,base_plus,large \
    --reference-mm srce=200,figura8=220,ploca=150 \
    --out benchmark_report
```

**Dostaviti:** `benchmark_report/benchmark.json` i `benchmark_report/BENCHMARK.md`
i, ako može, tačan čip i broj GPU jezgara (`system_profiler SPHardwareDataType SPDisplaysDataType`).

Očekivano: `set_image` za `small` ~0,05–0,3 s; `large` mora da staje u
unified memory. Ako MPS padne na CPU fallback, navedi to u izveštaju.

## 3. Fizičke provere

### 3.1 Faza 0a — skala, kerf i probni rez

**Cilj:** potvrditi da SVG u LightBurn-u ima tačne milimetre i izmeriti kerf
vaše mašine/materijala.

**Korak 1 — kalibracioni kvadrati:**

```bash
uv run lampcutter calibrate --sizes 100,20,30,40 --out proba/kalibracija
```

- Uvezi `proba/kalibracija/kalibracija.svg` u LightBurn.
- **Proveri:** u polju „Size" kvadrat od 100 mm mora pokazati **100,0 mm**
  (tolerancija ±0,1 mm); svi elementi u crvenom sloju (`#FF0000`).
- Odseci, pa **izmeri** svaki kvadrat pomičnim merilom (u oba pravca) i upiši:

| nominalno | izmereno X | izmereno Y | kerf X (nom−iz) | kerf Y (nom−iz) |
|---|---|---|---|---|
| 100 mm | | | | |
| 20 mm | | | | |
| 30 mm | | | | |
| 40 mm | | | | |

**Korak 2 — upiši kerf u profil materijala:**

```bash
cp tests/data/materials_proba.json proba/materials.json   # ako još nije
uv run lampcutter calibrate --sizes 100,20,30,40 \
    --measured 99.82,19.83,29.76,39.71 \
    --materials-file proba/materials.json --material acrylic-3
```

(izmerene vrednosti zameni svojim; prosek se upisuje u `proba/materials.json`)

**Korak 3 — probni komad iz slike:**

```bash
uv run lampcutter run tests/data/srce.png --mask-file tests/data/ref/srce.png \
    --height-mm 200 --material acrylic-3 --materials-file proba/materials.json \
    --out proba/0a --debug-dir proba/0a/debug
```

- Program ispiše dimenzije (npr. „Dimenzije: 204,73 × 200,00 mm"); u LightBurn-u
  izmeri visinu izrezanog dela — mora da odgovara onome što je program ispisao
  (±0,2 mm, uz kerf).
- Uvezi SVG, iseci, izmeri: visina, širina, kerf na ivicama.

**Dostaviti:** tabelu merenja, `proba/materials.json`, fotografiju probnog reza.

### 3.2 Faza 0b — jezičak i prorez baze

**Cilj:** jezičak ulazi u prorez baze bez prisile i bez klimanja; potvrditi
pravila zazora iz spec 8.3.

**Korak 1 — pripremi profil baze.** Izmeri svoju bazu:

- dužina proreza u ravni ploče (`slot_length_mm`),
- širina proreza po debljini akrila (`slot_thickness_mm`),
- željena širina jezička `tab_width_mm` (obično `slot_length_mm` − 0,2…0,4 mm),
- dubina ulaska `tab_height_mm`.

```bash
cp tests/data/base_proba.json proba/moja_baza.json
```

Uredi vrednosti u `proba/moja_baza.json` (id ostavi `moja-baza`).

**Korak 2 — generiši komad sa jezičkom:**

```bash
uv run lampcutter run tests/data/ploca.png --mask-file tests/data/ref/ploca.png \
    --height-mm 150 --material acrylic-3 --materials-file proba/materials.json \
    --base moja-baza --bases-file proba/moja_baza.json --out proba/0b
```

Program ispiše: efektivnu dužinu proreza, **zazor u ravni** i **zazor po
debljini** + upozorenja ako je zazor negativan (neće ući) ili > 1,0 mm (klima).

- Uvezi `proba/0b/lamp_cut.svg` u LightBurn, iseci.
- **Proveri:** jezičak ulazi u prorez bez prisile; nema klimanja; izmeri zazor.
- Ako je previše široko: smanji `tab_fit_mm` (npr. −0,2) i ponovi; ako je
  previše usko: povećaj.

| stavka | izmereno | ocena (ulazi / klima / ne ulazi) |
|---|---|---|
| zazor u ravni | | |
| zazor po debljini | | |
| jezičak u prorezu | | |

**Dostaviti:** `proba/moja_baza.json`, tabelu, fotografiju sklopljenog dela.

### 3.3 Faza 1 — gravura i štampa

**Cilj:** gravura ide u plavi sloj i ne seče se; štampa se poravnava sa rezom.

**Korak 1 — izvezi demo šablon:**

```bash
uv run lampcutter export --template tests/data/demo.lamptpl --out proba/1a --print-dpi 300
```

Dobijaš: `lamp_cut.svg` (cut crveno + gravura plavo), `print_sheet.png`,
`photo_01_foto-1.png`, `decor_01_stampa-tekst.png`, `manifest.json`.

**Korak 2 — LightBurn provera:**

- Uvezi `lamp_cut.svg`; **proveri:** postoje dva sloja — crveni `#FF0000`
  (sečenje) i plavi `#0000FF` (gravura); gravura je unutar konture sa marginom
  ~1,5 mm; dimenzije dela odgovaraju (180 × 230 mm + jezičak 8 mm = 188 × 238 mm
  nominal, u LightBurn-u proveri „Size" selekcije).
- Uključi samo crveni sloj → iseci. Uključi plavi → graviraj (ili prema
  podešavanjima za gravuru).
- **Proveri:** gravura je vidljiva, unutar komada, nije prorezana kroz materijal.

**Korak 3 — poravnanje štampe:**

- Odštampaj `print_sheet.png` na UV štampaču (ili na običnom štampaču na papiru
  sa 100% skalom za probu).
- **Proveri:** 4 registraciona krstića u uglovima; izmeri rastojanje između
  krstića i uporedi sa vrednostima iz `manifest.json`
  (`sheet_size_mm`, `origin_offset_mm`).
- Ako je moguće: odštampaj na akril i uporedi sa izrezanim komadom.
- **Tolerancija poravnanja (spec 13.4):** oko **0,15 mm** za lampe do 200 mm i
  **0,3 mm** za veće.

| provera | izmereno | tolerancija | ocena |
|---|---|---|---|
| krstić 1–2 (širina) | | 0,15–0,3 mm | |
| krstić 1–3 (visina) | | 0,15–0,3 mm | |
| poklapanje foto slota sa rezom | | 0,15–0,3 mm | |
| efektivni DPI (iz manifesta) | | ≥ 150 | |

**Dostaviti:** `proba/1a/` (svg, manifest, print sheet), tabelu, fotografije
gravure i štampe, rezultat uvoza u LightBurn (screenshot je dovoljan).

## 4. Faza E — ulazni materijal za eksperiment segmentacije

Potrebno je **2–3 stvarne fotografije upaljene lampe** (ne mockup) i
**2–3 mockupa sa poznatim stvarnim visinama** (spec 13.3 i 17):

- frontalni snimak, kamera približno normalno na ravan lampe;
- poznata visina izrezanog dela u mm (bez jezička);
- format JPG/PNG/WEBP, preporuka > 1500 px po dužoj strani;
- ako imaš, priloži i referentne maske (PNG, bela = lampa).

Imenovanje i tabela:

| fajl | tip (foto/mockup) | visina mm | napomena |
|---|---|---|---|
| `foto_srce_200mm.jpg` | foto | 200 | upaljena lampa, front |
| `mockup_porodica_250mm.png` | mockup | 250 | render |

Fajlove stavi u `tests/data/private/` (gitignore) ili pošalji arhivom; u
`proba/faza-e/` ako želiš da idu kroz PR.

## 5. Šta vratiti i kako

**Preporučeno:** GitHub PR sa:

- `benchmark_report/benchmark.json` + `BENCHMARK.md` (Mac),
- `proba/` sa tabelama (može i kao `proba/verifikacija/REZULTATI.md`),
- fotografijama probnih rezova, gravure i štampe,
- `proba/materials.json`, `proba/moja_baza.json`, `proba/1a/manifest.json`.

Alternativno: issue u repou sa nalazima, ili pošalji korisniku pa će on dostaviti
meni.

**Format tabele za nalaze:**

```markdown
## Nalaz
- šta je provereno:
- očekivano (spec):
- dobijeno:
- dokaz (fajl/komanda/fotografija):
```

## 6. Kriteriji prihvatanja (spec 13.4)

| provera | kriterij |
|---|---|
| LightBurn dimenzije | kvadrat 100 mm → 100,0 ± 0,1 mm |
| kerf po materijalu | konzistentan po kvadratima; upisan u profil |
| jezičak | ulazi bez prisile, bez klimanja; zazor u ravni 0…1 mm |
| gravura | sloj `#0000FF`, unutar konture sa marginom, ne seče |
| poravnanje štampe | ~0,15 mm (do 200 mm), ~0,3 mm (veće) |
| efektivni DPI fotografija | ≥ 150 |
| vreme obrade | CPU: < 15 s sa `small`; GPU/MPS: < 3 s po slici |

## 7. Checklist

- [ ] GitHub pozivnica prihvaćena, repo kloniran, `uv sync` prošao
- [ ] Mac benchmark: `benchmark_report/benchmark.json` + `BENCHMARK.md` dostavljeni
- [ ] Faza 0a: LightBurn dimenzije kvadrata tačne
- [ ] Faza 0a: kerf izmeren i upisan u `proba/materials.json`
- [ ] Faza 0a: probni komad iz `srce.png` isečen i izmeren
- [ ] Faza 0b: profil baze popunjen stvarnim merama
- [ ] Faza 0b: komad sa jezičkom isečen; jezičak nalegao
- [ ] Faza 1: gravura u plavom sloju, unutar konture, ne seče
- [ ] Faza 1: print sheet odštampan 1:1; registracione oznake izmerene
- [ ] Faza 1: poravnanje štampe i reza u toleranciji
- [ ] Faza E: fotografije/mockupi sa visinama dostavljeni (ili dogovoren rok)
- [ ] Nalazi dokumentovani (PR/issue) i poslati DSH-u za obradu

## 8. Napomene

- Ako nešto od komandi ne radi, pošalji **tačnu komandu, izlaz i grešku** — ne
  prilagođavaj kod sam (implementaciju i testove drže DSH i Agi).
- `uv run` bez `--no-sync` vraća okruženje na stanje iz locka i uklanja ML
  pakete — zato je svuda naveden `--no-sync` za ML komande.
- Zaključani test setovi se proveravaju sa:
  `uv run python scripts/run_cases.py tests/cases/phase0a.json` (isto za
  `phase0b`, `phase1`).
