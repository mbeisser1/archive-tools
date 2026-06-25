#!/usr/bin/env python3
"""Recursively rename files so each basename uses only lowercase letters."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rename every file under DIR so the basename uses only lowercase letters. "
            "Directory names are left unchanged. Processes deepest paths first."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  rename-lowercase.py -d ./takeout -n
      → Foobar.JPG becomes foobar.jpg (basename only; dirs unchanged)

  rename-lowercase.py -d /pool/archive/cloud_backups/immich/upload
""",
    )
    parser.add_argument("-d", metavar="DIR", required=True, help="Root directory")
    parser.add_argument("-n", action="store_true", help="Dry-run — print renames only")
    return parser


def rename_file(src: Path, *, dry_run: bool) -> str:
    """Return 'renamed', 'unchanged', or 'conflict'."""
    lower_name = src.name.lower()
    if src.name == lower_name:
        return "unchanged"

    dest = src.parent / lower_name
    if dry_run:
        print(f"rename: {src} -> {dest}")
        return "renamed"

    if dest.exists():
        try:
            if src.samefile(dest):
                with tempfile.NamedTemporaryFile(dir=src.parent, delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                src.rename(tmp_path)
                tmp_path.rename(dest)
                return "renamed"
        except OSError:
            pass
        print(f"skip (conflict): {src} -> {dest}", file=sys.stderr)
        return "conflict"

    src.rename(dest)
    return "renamed"


def iter_files_deepest_first(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root, topdown=False):
        base = Path(dirpath)
        for name in filenames:
            files.append(base / name)
    return files


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    root = Path(args.d).expanduser().resolve()
    if not root.is_dir():
        print(f"error: directory not found: {root}", file=sys.stderr)
        return 1

    print(f"Directory: {root}")
    if args.n:
        print("Mode:      dry-run")

    renamed = 0
    conflicts = 0
    skipped = 0

    for path in iter_files_deepest_first(root):
        result = rename_file(path, dry_run=args.n)
        if result == "renamed":
            renamed += 1
        elif result == "conflict":
            conflicts += 1
            skipped += 1

    print(f"Renamed:   {renamed}")
    if conflicts:
        print(f"Conflicts: {conflicts}", file=sys.stderr)
    if skipped:
        print(f"Skipped:   {skipped}", file=sys.stderr)

    if conflicts:
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
