"""Rename .jpeg files to .jpg with collision-safe suffixes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

JPEG_SUFFIX = ".jpeg"
CANONICAL_SUFFIX = ".jpg"


def is_jpeg(path: Path) -> bool:
    return path.suffix.casefold() == JPEG_SUFFIX


def resolve_dest(src: Path) -> Path:
    """Pick a .jpg path; suffix _N when stem.jpg is already taken."""
    parent = src.parent
    stem = src.stem
    candidate = parent / f"{stem}{CANONICAL_SUFFIX}"
    if not candidate.exists():
        return candidate

    try:
        if src.samefile(candidate):
            return candidate
    except OSError:
        pass

    suffix = 1
    while True:
        alt = parent / f"{stem}_{suffix}{CANONICAL_SUFFIX}"
        if not alt.exists():
            return alt
        try:
            if src.samefile(alt):
                return alt
        except OSError:
            pass
        suffix += 1
        if suffix > 10_000:
            raise RuntimeError(f"too many collisions for {src}")


def rename_jpeg_file(
    src: Path, *, dry_run: bool
) -> tuple[str, Path | None, str]:
    """Return status ('renamed', 'unchanged', 'error'), dest, and message."""
    if not is_jpeg(src):
        return "unchanged", None, ""

    dest = resolve_dest(src)
    if dest == src:
        return "unchanged", None, ""

    if dry_run:
        return "renamed", dest, ""

    if dest.exists():
        try:
            if src.samefile(dest):
                with tempfile.NamedTemporaryFile(dir=src.parent, delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                src.rename(tmp_path)
                tmp_path.rename(dest)
                return "renamed", dest, ""
        except OSError:
            pass
        return "error", dest, "destination already exists"

    src.rename(dest)
    return "renamed", dest, ""


def iter_jpeg_files_deepest_first(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root, topdown=False):
        base = Path(dirpath)
        for name in filenames:
            path = base / name
            if is_jpeg(path):
                files.append(path)
    return files
