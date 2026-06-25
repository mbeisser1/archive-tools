#!/usr/bin/env python3
"""Recursively rename files so each basename uses only lowercase letters."""

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rename every file under DIR so the basename uses only lowercase letters. "
            "Directory names are left unchanged. Processes deepest paths first."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  rename-lowercase.py -d ./takeout
      → Foobar.JPG becomes foobar.jpg (basename only; dirs unchanged)

  rename-lowercase.py -d ./takeout -x
      → apply renames; writes rename-lowercase_YYYY-mm-DD__HH_MM_SS.log
""",
    )
    parser.add_argument("-d", metavar="DIR", required=True, help="Root directory")
    add_execute_arg(parser)
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        metavar="FILE",
        help="TSV log path when executing (default: rename-lowercase_YYYY-mm-DD__HH_MM_SS.log)",
    )
    return parser


def rename_file(src: Path, *, dry_run: bool) -> tuple[str, Path | None, str]:
    """Return status ('renamed', 'unchanged', 'conflict'), dest, and message."""
    lower_name = src.name.lower()
    if src.name == lower_name:
        return "unchanged", None, ""

    dest = src.parent / lower_name
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
        return "conflict", dest, "destination already exists"

    src.rename(dest)
    return "renamed", dest, ""


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

    dry_run = not args.execute
    log = TsvLog(
        tool="rename-lowercase.py",
        input_path=root,
        output_path=None,
        dry_run=dry_run,
        log_path=run_log_path("rename-lowercase", root, args.log),
    )

    print(f"Directory: {root}")
    if dry_run:
        print("Mode:      dry-run")

    for path in iter_files_deepest_first(root):
        bytes_in = None
        bytes_out = None
        if not dry_run:
            try:
                bytes_in = path.stat().st_size
            except OSError:
                pass

        result, dest, message = rename_file(path, dry_run=dry_run)
        if result == "unchanged":
            continue
        if result == "renamed":
            if not dry_run and dest is not None:
                try:
                    bytes_out = dest.stat().st_size
                except OSError:
                    pass
            log.write(LogEntry(
                operation="lowercase",
                status=STATUS_DRY_RUN if dry_run else STATUS_OK,
                source=path,
                dest=dest,
                action="rename",
                bytes_in=bytes_in,
                bytes_out=bytes_out,
            ))
            continue
        log.write(LogEntry(
            operation="lowercase",
            status=STATUS_ERROR,
            source=path,
            dest=dest,
            action="rename",
            message=message,
        ))

    return log.close()


if __name__ == "__main__":
    raise SystemExit(main())
