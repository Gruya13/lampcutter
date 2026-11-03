#!/usr/bin/env bash
# Lokalni CI: lint + zaključani test set sa blokiranom mrežom (specifikacija, 11.3).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== ruff check =="
uv run ruff check .

echo "== ruff format --check =="
uv run ruff format --check src scripts

echo "== zaključani test set (Faza 0a) =="
uv run python scripts/run_cases.py tests/cases/phase0a.json -- --disable-socket --allow-unix-socket
