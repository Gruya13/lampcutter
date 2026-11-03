# API ugovor — Faza 4 (distribucija)

Dopuna ugovora iz 0a/0b/1/2/3. Faza 4 pokriva distribuciju (spec 16):
verziju, samostalne PyInstaller pakete, release workflow i instalacijsko
uputstvo.

## Verzija i ulazne tačke

- `lampcutter.__version__` je `"0.4.0"`; `pyproject.toml` `[project].version`
  je isto (jedan izvor istine; `scripts/build.py` je čita iz pyproject-a).
- `lampcutter --version` i `python -m lampcutter --version` ispisuju
  `lampcutter 0.4.0` i izlaze sa kodom 0 (preko `argparse` `action="version"`).
- CLI ima komande: `run`, `calibrate`, `export`, `gui`, `benchmark`
  i globalni `--version`.

## `scripts/build.py` — samostalan paket (PyInstaller)

```python
def project_version() -> str
def platform_tag() -> str
def build_command(args: argparse.Namespace) -> list[str]
def make_archive(args: argparse.Namespace) -> Path
def main(argv: list[str] | None = None) -> int
```

- `project_version()` vraća verziju iz `pyproject.toml` (npr. `"0.4.0"`).
- `platform_tag()` vraća tag oblika `linux-x86_64`, `macos-arm64`,
  `windows-x86_64` (zavisi od `sys.platform`/`platform.machine()`).
- `build_command(args)` vraća listu argumenata koji sadrže:
  `-m`, `PyInstaller`, `--noconfirm`, `--clean`, `--name`, `--distpath`,
  `--workpath`, `--paths <repo>/src`, `--collect-submodules`, `lampcutter`,
  `--console`, `--add-data` (prevodi), i na kraju
  `<repo>/src/lampcutter/__main__.py`; sa `onefile=True` sadrži `--onefile`.
- `make_archive(args)` zipuje `dist/<name>` (onedir) ili `dist/<name>.exe`
  (onefile) u `dist/<name>-<version>-<platform>.zip`; ako izlaz ne postoji →
  `FileNotFoundError`.
- `main(["--dry-run"])` ispiše komandu i vraća 0 **bez** pokretanja
  PyInstaller-a; `main([])` poziva `subprocess.run(..., check=True)`.
- `scripts/build.py --dry-run` iz korena repoa radi bez PyInstaller instalacije
  (samo ispiše komandu).

## `.github/workflows/release.yml` — release na tag

- YAML je validan (parsira se sa `yaml.safe_load`).
- Trigger: `on.push.tags: ["v*"]`; `permissions.contents: write`.
- `jobs.build` je matrica sa 3 OS (`ubuntu-latest`, `macos-latest`,
  `windows-latest`); svaki korak:
  - `actions/checkout@v4` sa **`fetch-depth: 0`**,
  - `astral-sh/setup-uv@v6` (Python 3.12),
  - `uv sync --group dev --extra gui`,
  - `uv run --no-sync python scripts/build.py --archive`,
  - `actions/upload-artifact@v4` sa `dist/*.zip`.
- `jobs.release` (`needs: build`) preuzima artefakte i koristi
  `softprops/action-gh-release@v2` sa `dist/*.zip`.

## `.github/workflows/ci.yml` — dopuna

- `actions/checkout@v4` ima `fetch-depth: 0` (lock proverava git revizije;
  shallow clone obara verifikaciju zaključanih testova).
- Zavisnosti: `uv sync --group dev --extra gui` (PySide6 i pytest-qt su u
  locku; GUI testovi rade offscreen).
- Test setovi: `phase0a phase0b phase1 phase2 phase3` (5 setova).

## `docs/INSTALACIJA.md` — instalacijsko uputstvo

Dokument sadrži sekcije (proverava se da postoje naslovi i ključne komande):

- preuzimanje sa GitHub Releases (imena arhiva `lampcutter-<verzija>-<platforma>.zip`),
- macOS Gatekeeper napomena (`xattr -dr com.apple.quarantine`),
- Linux biblioteke (Qt),
- prvi koraci (`--version`, `calibrate`, `run --mask-file`, `gui`),
- lokacije profila po sistemu,
- ML stack (torch + SAM 2, modeli, `fetch_models.py`),
- iz izvora (`uv sync --group dev --extra gui`),
- build (`scripts/build.py --archive`/`--onefile`/`--dry-run`),
- rešavanje problema.

## Format test seta

Isti kao ranije: Python pytest fajl se upisuje u wiki kao
`artifacts/tests-phase4.py`, DSH ga umotava u JSON i zaključava. Testovi su
okruženjski nezavisni: ne pokreću pravi PyInstaller build (samo `--dry-run` i
čiste funkcije), ne traže mrežu, ne učitavaju SAM 2; YAML se parsira sa
`yaml.safe_load` (pyyaml je u dev zavisnostima).
