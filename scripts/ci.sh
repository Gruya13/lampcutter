#!/usr/bin/env bash
# Lokalni CI: lint + zaključani test setovi (specifikacija, 11.3).
# GUI testovi rade offscreen i traže PySide6 + pytest-qt (instaliraju se ovde jer
# nisu u locku; ML stack iz FazE 0/1 se instalira odvojeno po potrebi).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== zavisnosti =="
uv sync --group dev
uv pip install "PySide6==6.12.0" "pytest-qt==4.5.0"

echo "== ruff check =="
uv run --no-sync ruff check .

echo "== ruff format --check =="
uv run --no-sync ruff format --check src scripts

for suite in phase0a phase0b phase1 phase2 phase3; do
  echo "== zaključani test set $suite =="
  QT_QPA_PLATFORM=offscreen uv run --no-sync python scripts/run_cases.py "tests/cases/$suite.json" \
      -- --disable-socket --allow-unix-socket
done