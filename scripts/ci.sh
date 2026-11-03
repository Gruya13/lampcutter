#!/usr/bin/env bash
# Lokalni CI: lint + zaključani test setovi sa blokiranom mrežom (specifikacija, 11.3).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== ruff check =="
uv run ruff check .

echo "== ruff format --check =="
uv run ruff format --check src scripts

for suite in phase0a phase0b phase1; do
  echo "== zaključani test set $suite =="
  uv run python scripts/run_cases.py "tests/cases/$suite.json" -- --disable-socket --allow-unix-socket
done
