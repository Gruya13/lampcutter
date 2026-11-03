# CHANGELOG

Format: Keep a Changelog. Faze iz `LAMPCUTTER_SPEC.md` (odeljak 16).

## [Unreleased]

### Dodato — Faza 0a

- Inicijalizacija repozitorijuma: struktura projekta, `pyproject.toml` sa
  egzaktnim pinovima i `uv.lock`, pytest/ruff konfiguracija, CI.
- `config.py`: podrazumevane vrednosti iz specifikacije 6.1, TOML učitavanje.
- `models.py`: dataclass-ovi iz specifikacije 5 (Prompt, SegmentationResult,
  ScaleInfo, MaterialProfile, BaseProfile, CutGeometry, PhotoSlot, DecorElement,
  LampTemplate).
- `settings.py`: profili materijala i baze (JSON u platformdirs folderu), sa
  PROVIZORNO označenim podrazumevanim vrednostima.
- `core/io_utils.py`: EXIF-safe učitavanje, SHA256, PNG sa DPI, radna veličina.
- `core/mask_ops.py`: komponente, popunjavanje rupa, morfologija, glađenje,
  ravna donja ivica, poligon u masku, `clean_mask`.
- `core/scale.py`: `mm_per_px` iz poznate dimenzije, kalibracija iz dve tačke.
- `core/vectorize.py`: Potrace backend + OpenCV/Chaikin fallback, adaptivno
  uzorkovanje Bezijea, y-nadole mm poligon.
- `core/geometry.py`: edge inset, rupe, simplifikacija, kerf offset, detekcija
  tankih delova, uklanjanje ivica kraćih od 0,02 mm (specifikacija 8.5).
- `core/svg_writer.py`: LightBurn SVG (mm, viewBox, sloj `#FF0000`, 3 decimale,
  bez transforma), validacija ponovnim učitavanjem.
- `core/pipeline.py`: orkestracija faze 0a + debug artefakti.
- `core/separation`: `device.py` (izbor uređaja, OOM lanac) i `segmentation.py`
  (SAM 2 omotač, `--mask-file`, lazy ML import).
- `cli.py`: `lampcutter run` sa tačkama, okvirom, maskom, materialom, kerf
  režimom i debug izlazom; `calibrate`/`benchmark` stubs za Fazu 0b.
- `scripts/benchmark.py` i `scripts/fetch_models.py` (specifikacija 11.2/11.3).
- Test-lock infrastruktura: `agent-probe/test-lock.mjs`, `.wiki` dokazni kanal,
  `scripts/run_cases.py` i API ugovor `docs/api-phase0a.md`.
- GitHub: privatni repo kao `main`; lokalni repo je staging.

### Test set Faze 0a (autor: agy)

- Nezavisan test set od 38 testova (mask_ops, scale, geometry kerf, vectorize,
  svg_writer, io_utils, device, config/models, pipeline end-to-end), upisan u
  wiki i zaključan kroz `agent-probe/test-lock.mjs` (38/38 prolazi).
- Posle prvog izvršavanja popravljena 4 implementaciona detalja gde je API
  ugovor bio nedorečen i 3 testa (autor, kroz `--relock` sa trajnim razlogom).

### Benchmark (CPU, prvi krug)

- Instaliran ML stack (torch 2.14.1+cpu, SAM 2 pinovan commit) i preuzeti svi
  SAM 2.1 checkpointi sa SHA256 manifestom.
- Sintetički benchmark uzorci (srce, figura-8, ploča) + referentne maske.
- Izmerena segmencija i end-to-end za tiny/small/base_plus/large:
  `small` 3,5 s end-to-end (cilj < 15 s na CPU ispunjen), `large` 2,2 GB RAM.
- Rezultati: `docs/benchmark/2026-11-03-cpu.md` (+ JSON). Benchmark na CUDA 4 GB
  i MPS ostaje za ciljne mašine.