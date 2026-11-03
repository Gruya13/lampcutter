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

### Dodato — Faza 3

- `core/project.py`: `.lampproj` projekti — putanja slike (relativna u folderu
  projekta), prompt ili ručni poligon, veličina/referenca, material_id/base_id,
  kerf/input_kind, putanja šablona; `save_project`/`load_project`, validacija
  šeme; maska se ne čuva (osim ručnog poligona).
- `ui/dialogs.py`: uređivači profila materijala (kerf, debljina, min detalj,
  napomene) i postolja (prorez, jezičak, zazor, radijus).
- `ui/i18n.py` + `resources/translations/`: `QTranslator` hook; srpski je
  izvorni, `.qm` fajlovi za druge jezike se dodaju bez promene koda.
- `ui.main_window.py`: čuvanje/otvaranje projekata i šablona, uređivači profila
  sa upisom u korisnički folder, dodavanje slotova/dekora iz poligona, izmena
  režima elementa, `.lamptpl` učitavanje u platno.
- `Prompt.positive`/`Prompt.negative`; `Canvas.load_prompt`/`load_polygon`;
  `SizePanel.set_reference`, `MaterialPanel.select_material`,
  `BasePanel.select_base`/`set_values`, `ContourPanel.set_values`.
- Zaključan test set Faze 3 (41 test, autor agy); ukupno 195 testova.

### Dodato — Faza 2

- `ui/tools.py` (Qt-free): `ViewTransform` (zum/pan matematički, `zoom_at` čuva
  tačku pod kursorom), `PromptBuilder` (pozitivne/negativne tačke, okvir, undo),
  `PolygonTool`, `GenerationCounter`.
- `ui/workers.py`: `TaskRunner` (`QThreadPool`, generacije — zastareli rezultati
  se odbacuju, `wait()` isporučuje queued rezultate, progress injekcija),
  `Debouncer` (150 ms za predikciju).
- `ui/canvas.py`: `QGraphicsView` platno — slika (EXIF), poluprozirna maska,
  kontura/slotovi/dekor u mm, zum točkićem, pan srednjim tasterom, prompt
  (L/R klik, drag okvir), poligon alat, undo.
- `ui/panels.py`: Veličina (mm/cm, S/M/L, izračunato), Materijal, Postolje
  (profili + zazor), Kontura, Elementi (slotovi/dekor sa režimom).
- `ui/main_window.py`: splitter, meni, drag&drop, pozadinski izvoz, otkazivanje,
  status; `ui/app.py` + `ui/theme.py` (tamna/svetla tema) i `lampcutter gui`.
- Zaključan test set Faze 2 (37 testova, autor agy, offscreen); ukupno 154 testa.

### Dodato — Faza 1

- `core/slots.py`: GeoJSON serijalizacija konture, slotova, dekora i celog
  šablona (`schema: 1`, zaokruživanje na 0,001 mm), `.lamptpl` save/load i
  validacija „pobeglog klika" (`validate_slot_mask`).
- `core/decor.py`: izdvajanje dekora pragom (luminansa/boja, Otsu adaptivni) i
  SAM maskom, režimi `engrave`/`print`/`none`, margina unutar konture i
  upozorenja za tanke linije.
- `core/compose.py`: foto slotovi (`cover`/`contain`, zoom, pan, rotacija,
  bleed), efektivni DPI sa upozorenjem < 150, `print_sheet.png` 1:1 sa
  registracionim oznakama i opcijom `cut_then_print`/`print_then_cut`,
  `photo_XX.png`, `decor_XX.png`, `manifest.json` i `export_bundle`.
- `svg_writer`: gravura ide u grupu `engrave` (`#0000FF`) bez kerf offseta.
- Zaključan test set Faze 1 (42 testa, autor agy): poravnanje, slotovi, dekor,
  serijalizacija; ukupno 117 testova u sva tri seta.

### Dodato — Faza 0b

- `geometry`: jezičak i prorez baze (8.3) — `add_tab`, `bottom_contact`,
  `slot_clearance`, `effective_slot_length`; `tab_fit`/tab_offset` sa
  zaobljenim uglovima; zazor se prijavljuje kroz upozorenja; posle kerfa jezičak
  ima tačno nominalnu širinu.
- `core/calibrate.py` + `lampcutter calibrate`: kalibracioni SVG bez kerfa,
  računanje `kerf = nominalno - izmereno` (prosek) i upis u profil materijala.
- `core/cache.py`: `PipelineCache` sa fazama S1–S6, digestima maski/poligona i
  brojačima za test invalidacije.
- `mask_ops.refine_edge`: GrabCut u uskoj traci oko ivice (stvarne fotografije).
- `pipeline`: `base` (jezičak), `segmenter` dependency injection, keš po fazama,
  `refine_edge` za `input_kind="photo"`, `clearance` u rezultatu.
- `cli`: `calibrate` komanda, `benchmark` delegira na `scripts/benchmark.py`,
  `run --base` stvarno dodaje jezičak.
- Zaključan test set Faze 0b (37 testova, autor agy) i relock Faze 0a
  (okruženjski nezavisna ispravka); ukupno 75 testova prolazi.

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