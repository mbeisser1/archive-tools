"""Lowercase file basenames with collision-safe _N suffixes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_MAX_SUFFIX = 10_000


def _name_available(
    src: Path,
    parent: Path,
    name: str,
    claimed: set[str] | None,
) -> bool:
    if claimed is not None and name in claimed:
        return False
    dest = parent / name
    if not dest.exists():
        return True
    try:
        return src.samefile(dest)
    except OSError:
        return False


def resolve_lowercase_dest(
    src: Path,
    *,
    claimed: set[str] | None = None,
) -> Path | None:
    """Return destination for lowercasing, or None if already lowercase."""
    if src.name == src.name.lower():
        return None

    parent = src.parent
    lower_stem = src.stem.lower()
    lower_ext = src.suffix.lower()
    base = f"{lower_stem}{lower_ext}"
    if _name_available(src, parent, base, claimed):
        return parent / base

    suffix = 1
    while suffix <= _MAX_SUFFIX:
        alt = f"{lower_stem}_{suffix}{lower_ext}"
        if _name_available(src, parent, alt, claimed):
            return parent / alt
        suffix += 1
    raise RuntimeError(f"too many collisions for {src}")


def rename_to_lowercase_file(
    src: Path,
    *,
    dry_run: bool,
    claimed: set[str] | None = None,
) -> tuple[str, Path | None, str]:
    """Return status ('renamed', 'unchanged', 'error'), dest, and message."""
    try:
        dest = resolve_lowercase_dest(src, claimed=claimed)
    except RuntimeError as exc:
        return "error", None, str(exc)
    if dest is None:
        return "unchanged", None, ""
    if dest == src:
        return "unchanged", None, ""

    if dry_run:
        if claimed is not None:
            claimed.add(dest.name)
        return "renamed", dest, ""

    if dest.exists():
        try:
            if src.samefile(dest):
                with tempfile.NamedTemporaryFile(dir=src.parent, delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                src.rename(tmp_path)
                tmp_path.rename(dest)
                if claimed is not None:
                    claimed.add(dest.name)
                return "renamed", dest, ""
        except OSError:
            pass
        return "error", dest, "destination already exists"

    src.rename(dest)
    if claimed is not None:
        claimed.add(dest.name)
    return "renamed", dest, ""


def iter_files_with_uppercase(root: Path) -> list[Path]:
    """Files under root whose basename is not all-lowercase (deepest first)."""
    files: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root, topdown=False):
        base = Path(dirpath)
        for name in filenames:
            if name != name.lower():
                files.append(base / name)
    return files
