#!/usr/bin/env python3
"""Rename .jpeg files to .jpg, resolving name collisions."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.cli_common import add_execute_arg  # noqa: E402
from lib.io_paths import run_log_path  # noqa: E402
from lib.tsv_log import LogEntry, STATUS_DRY_RUN, STATUS_ERROR, STATUS_OK, TsvLog  # noqa: E402

JPEG_SUFFIX = ".jpeg"
CANONICAL_SUFFIX = ".jpg"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rename every .jpeg file under DIR to .jpg. Existing .jpg files are "
            "left unchanged. Uses stem_1.jpg, stem_2.jpg, … when the target exists."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  rename-jpeg.py -d ./photos
      → photo.jpeg becomes photo.jpg; skips photo.jpg

  rename-jpeg.py -d ./photos -x
      → apply renames; writes rename-jpeg_YYYY-mm-DD__HH_MM_SS.log

  rename-jpeg.py -d ./photos
      → if photo.jpg and photo.jpeg both exist, photo.jpeg → photo_1.jpg
""",
    )
    parser.add_argument("-d", metavar="DIR", required=True, help="Root directory")
    add_execute_arg(parser)
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        metavar="FILE",
        help="TSV log path when executing (default: rename-jpeg_YYYY-mm-DD__HH_MM_SS.log)",
    )
    return parser


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


def rename_file(src: Path, *, dry_run: bool) -> tuple[str, Path | None, str]:
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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    root = Path(args.d).expanduser().resolve()
    if not root.is_dir():
        print(f"error: directory not found: {root}", file=sys.stderr)
        return 1

    dry_run = not args.execute
    log = TsvLog(
        tool="rename-jpeg.py",
        input_path=root,
        output_path=None,
        dry_run=dry_run,
        log_path=run_log_path("rename-jpeg", root, args.log),
    )

    print(f"Directory: {root}")
    if dry_run:
        print("Mode:      dry-run")

    for path in iter_jpeg_files_deepest_first(root):
        bytes_in = None
        bytes_out = None
        if not dry_run:
            try:
                bytes_in = path.stat().st_size
            except OSError:
                pass

        try:
            result, dest, message = rename_file(path, dry_run=dry_run)
        except RuntimeError as exc:
            log.write(LogEntry(
                operation="jpeg",
                status=STATUS_ERROR,
                source=path,
                action="rename",
                message=str(exc),
            ))
            continue

        if result == "unchanged":
            continue
        if result == "renamed":
            if not dry_run and dest is not None:
                try:
                    bytes_out = dest.stat().st_size
                except OSError:
                    pass
            log.write(LogEntry(
                operation="jpeg",
                status=STATUS_DRY_RUN if dry_run else STATUS_OK,
                source=path,
                dest=dest,
                action="rename",
                bytes_in=bytes_in,
                bytes_out=bytes_out,
            ))
            continue
        log.write(LogEntry(
            operation="jpeg",
            status=STATUS_ERROR,
            source=path,
            dest=dest,
            action="rename",
            message=message,
        ))

    return log.close()


if __name__ == "__main__":
    raise SystemExit(main())
