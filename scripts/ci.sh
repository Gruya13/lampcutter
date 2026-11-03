#!/usr/bin/env bash
# Lokalni CI: lint + testovi sa blokiranom mrežom (specifikacija, 11.3).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== ruff check =="
uv run ruff check .

echo "== ruff format --check =="
uv run ruff format --check .

echo "== pytest (mreža blokirana) =="
uv run pytest --disable-socket --allow-unix-socket "$@"
