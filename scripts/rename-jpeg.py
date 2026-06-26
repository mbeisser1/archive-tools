#!/usr/bin/env python3
"""Rename .jpeg files to .jpg, resolving name collisions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.cli_common import add_execute_arg  # noqa: E402
from lib.io_paths import run_log_path  # noqa: E402
from lib.jpeg_rename import (  # noqa: E402
    iter_jpeg_files_deepest_first,
    rename_jpeg_file,
)
from lib.tsv_log import LogEntry, STATUS_DRY_RUN, STATUS_ERROR, STATUS_OK, TsvLog  # noqa: E402


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
            result, dest, message = rename_jpeg_file(path, dry_run=dry_run)
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
