# API ugovor — v1.1 (ručna četkica za retuš maske)

Dopuna ugovora iz 0a/0b/1/2/3/4. Implementira v1.1 stavku iz spec
(odeljak 12.1, 17): ručna četkica za retuš maske posle segmentacije.

## `lampcutter.config.Config`

- novo polje `brush_radius_px: int = 25`; validacija: `1 <= brush_radius_px <= 500`,
  inače `ValueError`.

## `lampcutter.core.mask_ops.paint_stroke` (retuš maske)

```python
def paint_stroke(
    mask: np.ndarray,
    points: list[tuple[float, float]] | np.ndarray,
    radius_px: float,
    add: bool = True,
) -> np.ndarray
```

- Vraća **novu** bool masku istog oblika; ulazna maska se ne menja.
- Potez je okrugla četkica poluprečnika `radius_px` duž polilinije `points`
  (redosled tačaka); jedan piksel kao tačka → krug.
- `add=True` dodaje piksele u masku, `add=False` ih uklanja.
- Tačke van granica se iseckaju (OpenCV clip), ne bacaju grešku.
- `radius_px <= 0` → `ValueError`; prazna lista tačaka ili pogrešan oblik →
  `ValueError`; maska nije 2-D → `ValueError`.
- Test: maska sa prazninom + `add=True` stroke preko praznine → ta površina je
  popunjena; `add=False` preko popunjenog dela → ta površina je prazna;
  `np.array_equal(mask, original)` posle poziva (original nepromenjen).

## `lampcutter.core.pipeline.revectorize_mask` (ponovna vektorizacija)

```python
def revectorize_mask(
    image_path, mask, *, config=None, material, base=None, input_kind="mockup",
    height_mm, reference="height", out_dir="izlaz", debug_dir=None,
    cache=None, progress=None, cancel=None,
) -> PipelineResult
```

- Preskače segmentaciju i radi **clean → scale → vectorize → geometry → export**
  (isti završni deo kao `run_pipeline`; `run_pipeline` je refaktorisan tako da
  dele `_finish_from_mask`, pa **ista maska daje isti SVG** kroz oba puta).
- Maska može biti bilo koje 2-D veličine; ako se ne poklapa sa slikom,
  resajzuje se na veličinu slike (NEAREST) pre ostatka.
- Prazna maska → `PipelineError`; pogrešan dimenzionalnost → `PipelineError`.
- Radi bez SAM 2 modela (test koristi `tests/data/srce.png`).
- `progress` i `cancel` rade isto kao u `run_pipeline`.

## `lampcutter.ui.canvas.Canvas` — brush režim

```python
MODE_BRUSH = "brush"
brush_stroke_finished = Signal(list, bool, int)  # points, add, radius_px

def set_brush(self, radius_px: int, add: bool = True) -> None
def begin_brush_stroke(self, image_point, add: bool = True) -> None
def extend_brush_stroke(self, image_point) -> None
def end_brush_stroke(self) -> tuple[list[tuple[float, float]], bool, int]
```

- `set_mode("brush")` je dozvoljen; nepoznat režim → `ValueError`.
- `set_brush` sa `radius_px <= 0` → `ValueError`; `brush_radius_px`/  `brush_add` se postavljaju.
- `begin_brush_stroke` započinje potez; `extend_brush_stroke` dodaje tačku
  (pomeraj < 0.5 px se ignoriše; pre početka poteza → `ValueError`);
  `end_brush_stroke` vraća `(points, add, radius)` i emituje
  `brush_stroke_finished` sa istim vrednostima; `end` bez početka →
  `ValueError`; posle `end` potez je resetovan.
- Tačke su u **pikselima slike** (kao i prompt).
- Režim `brush` ne dira prompt/poligon.

## `lampcutter.ui.panels.BrushPanel` — panel četkice

```python
class BrushPanel(QGroupBox):
    brush_changed = Signal(int, bool)  # radius_px, add
    undo_requested = Signal()
    radius_spin / mode_combo / undo_button
    def radius_px() -> int
    def add_mode() -> bool
    def set_from_config(config) -> None
```

- Promena radijusa ili režima emituje `brush_changed(radius_px, add)`;
  klik na dugme emituje `undo_requested`.
- `mode_combo` ima dva režima: `True` = dodaj, `False` = ukloni.

## `lampcutter.ui.main_window.MainWindow` — integracija retuša

```python
brush_mask: np.ndarray | None      # trenutna maska za retuš
brush_history: list[np.ndarray]    # istorija maski (max 10)
def _on_brush_stroke(points, add, radius_px) -> None
def _revectorize() -> None
def _retouch_job(progress=None) -> PipelineResult
def _on_retouch_result(result) -> None
```

- `_on_brush_stroke`: ako `brush_mask`/slika nisu postavljeni → status poruka i
  `last_error`, **bez pada**; inače primeni `paint_stroke`, sačuva staru masku
  u `brush_history` (najviše 10), postavi `canvas` masku i zakaže
  revektorizaciju (debounce 250 ms).
- Debounce → `_revectorize` pokreće `revectorize_mask` u workeru; rezultat
  stiže u `_on_retouch_result` koji **ne resetuje** `brush_history` i
  `brush_mask` postavlja iz `result.mask_clean`.
- `undo()` u brush režimu: ako ima istorije, vrati prethodnu masku i pokreni
  revektorizaciju; inače se ponaša kao ranije (canvas undo).
- `load_image` i prvi `_on_result` resetuju `brush_mask`/`brush_history`.
- GUI testovi ne zahtevaju SAM 2: postavi `window.brush_mask` ručno i
  monkeypatch-uj `lampcutter.ui.main_window.revectorize_mask` gde treba;
  za pravi revektoriz test koristi `tests/data/srce.png` i malu masku.

## Format test seta

Isti kao ranije: Python pytest fajl se upisuje u wiki kao
`artifacts/tests-brush.py`, DSH ga umotava u JSON i zaključava. GUI testovi
offscreen kao u Fazi 2/3.
