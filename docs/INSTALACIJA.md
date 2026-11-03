# Instalacija i distribucija

Lampcutter se distribuira kao samostalan paket (PyInstaller) preko
[GitHub Releases](https://github.com/Gruya13/lampcutter/releases) i može da se
pokrene bez instaliranja Pythona. Za razvoj iz izvora vidi kraj dokumenta.

## Šta je u paketu

- Grafički interfejs (`lampcutter gui`) sa platnom, panelima, projektima i
  šablonima.
- CLI: `run` (sa `--mask-file` ili ručnim poligonom), `calibrate`,
  `export`, `benchmark`, `--version`.
- **Lite paket ne sadrži ML stack** (torch + SAM 2) — segmentacija iz slike
  zahteva instalaciju izvora (vidi „ML stack" ispod). Bez ML stacka radi sve
  ostalo: `--mask-file`, ručni poligon, `calibrate`, `export`, GUI, štampa.

## Preuzimanje

1. Otvori GitHub Releases i preuzmi arhivu za svoj sistem:
   - `lampcutter-0.4.0-linux-x86_64.zip`
   - `lampcutter-0.4.0-macos-arm64.zip`
   - `lampcutter-0.4.0-windows-x86_64.zip`
2. Raspakuj u folder po želji (npr. `~/lampcutter`).
3. Pokreni:
   - Linux/macOS: `./lampcutter/lampcutter` (ili `./lampcutter/lampcutter gui`)
   - Windows: `lampcutter\lampcutter.exe` (ili `lampcutter.exe gui`)

### macOS napomena (Gatekeeper)

Paket nije potpisan. Ako macOS blokira pokretanje:
```bash
xattr -dr com.apple.quarantine ~/lampcutter
# ili: desni klik na lampcutter → Open → Open
```

### Linux napomena

Ako Qt prijavi nedostajuće biblioteke, instaliraj osnovne:
```bash
sudo apt install libgl1 libegl1 libxkbcommon0   # Debian/Ubuntu
sudo pacman -S mesa libxkbcommon               # Arch
```

## Prvi koraci

```bash
# ručna provera
./lampcutter --version

# kalibracija kerfa (kvadrati 100/20/30/40 mm)
./lampcutter calibrate --sizes 100,20,30,40 --out proba/kalibracija

# obrada slike sa postojećom maskom (bez modela)
./lampcutter run slika.png --mask-file maska.png --height-mm 200 --out izlaz

# grafički interfejs
./lampcutter gui
```

Profili materijala i baza čuvaju se u korisničkom folderu:

| Sistem | Putanja |
|---|---|
| Linux | `~/.config/lampcutter/` |
| macOS | `~/Library/Application Support/lampcutter/` |
| Windows | `%APPDATA%\\lampcutter\\` |

## ML stack (SAM 2 segmentacija iz slike)

Lite paket ne uključuje torch i SAM 2. Za segmentaciju iz slike:

```bash
# u razvojnom okruženju (vidi „iz izvora”)
uv pip install torch==2.14.1 torchvision==0.29.1
uv pip install setuptools wheel hydra-core iopath tqdm
uv pip install --no-build-isolation \
    "sam-2 @ git+https://github.com/facebookresearch/sam2.git@2b90b9f5ceec907a1c18123530e92e794ad901a4"
uv run --no-sync python scripts/fetch_models.py --variants tiny,small
uv run --no-sync python scripts/fetch_models.py --verify
```

Modeli se preuzimaju jednom i čuvaju u `models/` (manifest sa SHA256 je u
repou). Detalji: `docs/benchmark/UPUTSTVO-ZA-AGENTA.md` i `README.md`.

## Iz izvora (razvoj)

```bash
git clone https://github.com/Gruya13/lampcutter.git
cd lampcutter
uv sync --group dev --extra gui
uv run lampcutter --version
uv run lampcutter gui
```

Testovi (offscreen GUI, 195 zaključanih testova):
```bash
./scripts/ci.sh
```

## Build paketa

```bash
uv run python scripts/build.py --archive           # dist/lampcutter-<verzija>-<platforma>.zip
uv run python scripts/build.py --onefile --archive # jedan izvršni fajl
uv run python scripts/build.py --dry-run           # samo prikaži PyInstaller komandu
```

Release workflow (`.github/workflows/release.yml`) na tag `v*` pravi pakete za
Linux, macOS (Intel/ARM runner) i Windows i kači ih na GitHub Release.
Version se čita iz `pyproject.toml`.

## Rešavanje problema

| Simptom | Rešenje |
|---|---|
| `lampcutter: command not found` | pokreni iz raspakovanog foldera sa `./lampcutter/lampcutter` |
| Qt greška o platformi | `QT_QPA_PLATFORM=offscreen` za headless; na desktopu `xcb`/`wayland` |
| „Model nije instaliran" | lite paket nema SAM 2 — koristi `--mask-file`/poligon ili instaliraj ML stack |
| macOS blokira | `xattr -dr com.apple.quarantine ~/lampcutter` |
| macOS: `No module named lampcutter` posle `uv sync` | `chflags nohidden .venv/lib/python3.12/site-packages/*.pth` (skriveni `.pth` se preskače) |
| Sporo pokretanje GUI-ja | prvi start učitava Qt; sledeći su brži |