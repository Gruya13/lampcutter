#!/usr/bin/env python3
"""Build standalone Lampcutter bundles for distribution (spec 16, Faza 4).

The default build is the "lite" bundle: GUI + CLI with `--mask-file`/manual
polygon and no ML stack, because torch + SAM 2 would make the archive several
gigabytes. Install the ML stack into the build environment first when a full
bundle is needed.

Usage:
    uv run python scripts/build.py                  # onedir bundle in dist/
    uv run python scripts/build.py --onefile        # single executable
    uv run python scripts/build.py --archive        # also write a .zip
    uv run python scripts/build.py --dry-run        # print the PyInstaller command
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
TRANSLATIONS_DIR = ROOT / "resources" / "translations"


def project_version() -> str:
    """Version declared in pyproject.toml (single source of truth for builds)."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def platform_tag() -> str:
    """Readable platform tag, e.g. `linux-x86_64` or `macos-arm64`."""
    systems = {"linux": "linux", "darwin": "macos", "win32": "windows"}
    machines = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}
    system = systems.get(sys.platform, sys.platform)
    machine = machines.get(platform.machine().lower(), platform.machine().lower())
    return f"{system}-{machine}"


def build_command(args: argparse.Namespace) -> list[str]:
    """The PyInstaller command line for one bundle."""
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        args.name,
        "--distpath",
        str(Path(args.dist_dir)),
        "--workpath",
        str(Path(args.work_dir)),
        "--paths",
        str(ROOT / "src"),
        "--collect-submodules",
        "lampcutter",
        "--console",
    ]
    if args.onefile:
        command.append("--onefile")
    if TRANSLATIONS_DIR.is_dir():
        command.extend(["--add-data", f"{TRANSLATIONS_DIR}{os.pathsep}resources/translations"])
    command.append(str(ROOT / "src" / "lampcutter" / "__main__.py"))
    return command


def make_archive(args: argparse.Namespace) -> Path:
    """Zip the built bundle into `dist/lampcutter-<version>-<platform>.zip`."""
    dist_dir = Path(args.dist_dir)
    source = dist_dir / (f"{args.name}.exe" if sys.platform == "win32" else args.name)
    if not source.is_dir():
        source = dist_dir / args.name
    if not source.exists():
        raise FileNotFoundError(f"build output not found: {source}")
    zip_path = dist_dir / f"{args.name}-{project_version()}-{platform_tag()}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        if source.is_dir():
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=Path(source.name) / path.relative_to(source))
        else:
            archive.write(source, arcname=source.name)
    return zip_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a standalone Lampcutter bundle.")
    parser.add_argument("--name", default="lampcutter", help="bundle name")
    parser.add_argument("--dist-dir", default=str(DIST_DIR), help="PyInstaller dist dir")
    parser.add_argument("--work-dir", default=str(BUILD_DIR), help="PyInstaller work dir")
    parser.add_argument("--onefile", action="store_true", help="single executable")
    parser.add_argument("--archive", action="store_true", help="also create a .zip")
    parser.add_argument("--dry-run", action="store_true", help="print the command only")
    args = parser.parse_args(argv)
    command = build_command(args)
    print(" ".join(command))
    if args.dry_run:
        return 0
    subprocess.run(command, check=True, cwd=ROOT)
    if args.archive:
        print(f"Arhiva: {make_archive(args)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
