#!/usr/bin/env python3
"""Build-time SAM 2 checkpoint download (specification, 11.3).

The application never downloads anything at runtime. This script runs on the
build machine (or on the user's machine during installation) and records every
checkpoint in `models/manifest.json` with its SHA256 so the runtime can verify
what it loads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# SAM 2.1 checkpoints (specification, 7.3). The names mirror the installed sam2
# package; re-verify on upgrade.
CHECKPOINT_URLS: dict[str, str] = {
    "sam2.1_hiera_tiny.pt": (
        "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt"
    ),
    "sam2.1_hiera_small.pt": (
        "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt"
    ),
    "sam2.1_hiera_base_plus.pt": (
        "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt"
    ),
    "sam2.1_hiera_large.pt": (
        "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt"
    ),
}

MANIFEST_NAME = "manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(models_dir: Path) -> dict:
    path = models_dir / MANIFEST_NAME
    if not path.exists():
        return {"schema": 1, "checkpoints": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("checkpoints", {})
    return data


def write_manifest(models_dir: Path, manifest: dict) -> Path:
    path = models_dir / MANIFEST_NAME
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def download(url: str, destination: Path) -> None:
    tmp = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(url) as response, tmp.open("wb") as handle:
        total = int(response.headers.get("Content-Length", 0))
        done = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            if total:
                percent = 100 * done / total
                print(f"\r  {percent:5.1f}%  {done // (1024 * 1024)} MiB", end="", file=sys.stderr)
    print("", file=sys.stderr)
    tmp.replace(destination)


def fetch_one(name: str, models_dir: Path, force: bool) -> dict:
    url = CHECKPOINT_URLS[name]
    destination = models_dir / name
    if destination.exists() and not force:
        print(f"[fetch_models] {name}: već postoji", file=sys.stderr)
    else:
        print(f"[fetch_models] {name}: preuzimam sa {url}", file=sys.stderr)
        download(url, destination)
    checksum = sha256_file(destination)
    return {
        "sha256": checksum,
        "bytes": destination.stat().st_size,
        "source": url,
        "recorded_at": datetime.now(UTC).isoformat(),
    }


def verify_manifest(models_dir: Path) -> int:
    """Check the downloaded checkpoints against the manifest; 0 = all good."""
    manifest = read_manifest(models_dir)
    failures = 0
    for name, entry in manifest["checkpoints"].items():
        path = models_dir / name
        if not path.exists():
            print(f"[verify] {name}: nema fajla", file=sys.stderr)
            failures += 1
            continue
        actual = sha256_file(path)
        if actual != entry.get("sha256"):
            print(f"[verify] {name}: SHA256 se ne poklapa", file=sys.stderr)
            failures += 1
        else:
            print(f"[verify] {name}: OK")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preuzmi SAM 2 checkpoint-e i upiši SHA256 u models/manifest.json"
    )
    parser.add_argument("--models-dir", type=Path, default=Path("models"))
    parser.add_argument(
        "--variants",
        default="tiny,small,base_plus,large",
        help="lista checkpoint-a: tiny,small,base_plus,large",
    )
    parser.add_argument("--force", action="store_true", help="ponovo preuzmi postojeće")
    parser.add_argument("--verify", action="store_true", help="samo proveri manifest")
    args = parser.parse_args(argv)

    args.models_dir.mkdir(parents=True, exist_ok=True)
    if args.verify:
        return verify_manifest(args.models_dir)

    selected = {
        "tiny": "sam2.1_hiera_tiny.pt",
        "small": "sam2.1_hiera_small.pt",
        "base_plus": "sam2.1_hiera_base_plus.pt",
        "large": "sam2.1_hiera_large.pt",
    }
    names = []
    for variant in args.variants.split(","):
        variant = variant.strip()
        if variant not in selected:
            print(f"Nepoznata varijanta {variant!r}", file=sys.stderr)
            return 2
        names.append(selected[variant])

    manifest = read_manifest(args.models_dir)
    for name in names:
        manifest["checkpoints"][name] = fetch_one(name, args.models_dir, args.force)
    write_manifest(args.models_dir, manifest)
    print(f"Manifest: {args.models_dir / MANIFEST_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
