#!/usr/bin/env python3
"""Run a locked cases JSON set (specification, 13.1).

The test source belongs to its author (agy): this runner must not edit it. It
extracts the exact bytes from the cases file and executes them with pytest. If a
lock sidecar is present, the lock is checked first and execution is refused when
the test set changed (the same rule as `evidence.mjs`).

    uv run python scripts/run_cases.py tests/cases/phase0a.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / ".test-run"
LOCK_TOOL = ROOT / "agent-probe" / "test-lock.mjs"


def load_cases(path: Path) -> dict:
    """Read a cases file, stripping an optional wiki YAML frontmatter."""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            text = parts[2].lstrip("\n")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("cases fajl mora biti JSON objekat")
    source = data.get("source_text", data.get("source"))
    if not isinstance(source, str) or not source.strip():
        raise ValueError("cases fajl nema 'source_text' (izvorni pytest kod)")
    data["source"] = source
    return data


def check_lock(cases_path: Path) -> tuple[bool, str]:
    """Run test-lock check when a sidecar exists; refuse a changed test set."""
    sidecar = Path(str(cases_path) + ".lock.json")
    if not sidecar.exists():
        return (True, "nema lock fajla (razvojni režim)")
    if not LOCK_TOOL.exists():
        return (False, f"nedostaje {LOCK_TOOL}")
    completed = subprocess.run(
        ["node", str(LOCK_TOOL), "check", str(cases_path), "--require-git"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stdout + completed.stderr).strip()
        return (False, f"lock provera nije prošla (exit {completed.returncode}): {message}")
    return (True, "lock OK")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Izvrši zaključani test set")
    parser.add_argument("cases", type=Path, help="putanja do cases JSON fajla")
    parser.add_argument(
        "--skip-lock-check",
        action="store_true",
        help="preskoči proveru locka (samo za razvoj test seta)",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="dodatni argumenti za pytest (posle --)",
    )
    args = parser.parse_args(argv)

    if not args.cases.exists():
        print(f"Greška: cases fajl ne postoji: {args.cases}", file=sys.stderr)
        return 2

    if not args.skip_lock_check:
        ok, message = check_lock(args.cases)
        print(f"[lock] {message}", file=sys.stderr)
        if not ok:
            return 3

    try:
        data = load_cases(args.cases)
    except (ValueError, json.JSONDecodeError) as error:
        print(f"Greška: neispravan cases fajl: {error}", file=sys.stderr)
        return 2

    entry = str(data.get("entry") or "test_cases.py")
    if not entry.endswith(".py"):
        print("Greška: 'entry' mora biti .py fajl", file=sys.stderr)
        return 2
    RUN_DIR.mkdir(exist_ok=True)
    target = RUN_DIR / Path(entry).name
    target.write_text(data["source"], encoding="utf-8")

    command = [sys.executable, "-m", "pytest", "-q", str(target)]
    pytest_args = list(args.pytest_args or [])
    if pytest_args and pytest_args[0] == "--":
        pytest_args = pytest_args[1:]
    command.extend(pytest_args)
    case_count = len(data.get("cases", []))
    print(f"[cases] {args.cases} -> {target} ({case_count} id-jeva)", file=sys.stderr)
    completed = subprocess.run(command, cwd=ROOT, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
