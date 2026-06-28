#!/usr/bin/env python3
"""Recursively rename files so each basename uses only lowercase letters."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.cli_common import add_execute_arg  # noqa: E402
from lib.io_paths import run_log_path  # noqa: E402
from lib.lowercase_rename import (  # noqa: E402
    iter_files_with_uppercase,
    rename_to_lowercase_file,
)
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

    claimed: set[str] = set()
    for path in iter_files_with_uppercase(root):
        bytes_in = None
        bytes_out = None
        if not dry_run:
            try:
                bytes_in = path.stat().st_size
            except OSError:
                pass

        result, dest, message = rename_to_lowercase_file(
            path, dry_run=dry_run, claimed=claimed
        )
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
