#!/usr/bin/env python3
"""Rename or copy media files using EXIF capture timestamps."""

from __future__ import annotations

import argparse
import shutil
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.cli_common import add_io_args  # noqa: E402
from lib.exif_rename import (  # noqa: E402
    already_renamed_pattern,
    iter_media_files,
    next_available_name,
    read_capture_datetime,
    require_exiftool,
)
from lib.io_paths import IoPlan, resolve_io, run_log_path  # noqa: E402
from lib.tsv_log import LogEntry, STATUS_DRY_RUN, STATUS_ERROR, STATUS_OK, STATUS_SKIP, TsvLog  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rename or copy media from EXIF capture time.",
        epilog=(
            "Default (no -o): rename in place.\n"
            "With -o: copy to output tree with new names; originals kept.\n"
            "Formats: YYYY-mm-DD__HH-MM-SS-{label}.ext or {label}-YYYY-mm-DD__HH-MM-SS.ext with --prefix"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_io_args(parser)
    parser.add_argument("--label", required=True, help="Suffix or prefix for generated names")
    parser.add_argument(
        "--prefix",
        action="store_true",
        help="Treat --label as prefix: {LABEL}-YYYY-mm-DD__HH-MM-SS.ext",
    )
    return parser


def collect_sources(plan: IoPlan) -> list[Path]:
    if plan.single_file:
        return [plan.input_path]
    return iter_media_files(plan.input_root)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    plan = resolve_io(args.input, args.output)
    dry_run = not args.execute
    log = TsvLog(
        tool="rename-exif.py",
        input_path=plan.input_path,
        output_path=plan.output_root or plan.output_path,
        dry_run=dry_run,
        log_path=run_log_path("rename-exif", plan, args.log),
    )

    try:
        exiftool = require_exiftool()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    pattern = already_renamed_pattern(args.label, use_prefix=args.prefix)
    claimed_by_dir: dict[Path, set[str]] = defaultdict(set)
    claimed_slots_by_dir: dict[Path, set[str]] = defaultdict(set)

    sources = collect_sources(plan)
    if args.list_only:
        for path in sources:
            print(path)
        print(f"# {len(sources)} file(s)", file=sys.stderr)
        return 0

    if not sources:
        print("No matching media files found.")
        return 0

    if plan.mirror and plan.output_root and not dry_run:
        plan.output_root.mkdir(parents=True, exist_ok=True)

    for source in sources:
        if pattern.match(source.name):
            log.write(LogEntry(
                operation="rename",
                status=STATUS_SKIP,
                source=source,
                message="already renamed",
            ))
            continue

        dt = read_capture_datetime(exiftool, source)
        if dt is None:
            log.write(LogEntry(
                operation="rename",
                status=STATUS_SKIP,
                source=source,
                message="no EXIF date",
            ))
            continue

        ext = source.suffix.lstrip(".")
        if plan.mirror and plan.output_root:
            from lib.io_paths import relative_to_root

            rel = relative_to_root(source, plan.input_root)
            dest_dir = plan.output_root / rel.parent
        else:
            dest_dir = source.parent

        new_name = next_available_name(
            args.label,
            dt,
            ext,
            dest_dir,
            use_prefix=args.prefix,
            claimed=claimed_by_dir[dest_dir],
            claimed_slots=claimed_slots_by_dir[dest_dir],
        )
        dest = dest_dir / new_name

        action = "copy" if plan.mirror else "rename"
        if source.name == new_name and not plan.mirror:
            log.write(LogEntry(
                operation="rename",
                status=STATUS_SKIP,
                source=source,
                dest=dest,
                action=action,
                message="unchanged",
            ))
            continue

        if dry_run:
            log.write(LogEntry(
                operation="rename",
                status=STATUS_DRY_RUN,
                source=source,
                dest=dest,
                action=action,
            ))
            continue

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if plan.mirror:
                shutil.copy2(source, dest)
            else:
                source.rename(dest)
            log.write(LogEntry(
                operation="rename",
                status=STATUS_OK,
                source=source,
                dest=dest,
                action=action,
                bytes_in=source.stat().st_size,
                bytes_out=dest.stat().st_size,
            ))
        except OSError as exc:
            log.write(LogEntry(
                operation="rename",
                status=STATUS_ERROR,
                source=source,
                dest=dest,
                action=action,
                message=str(exc),
            ))

    return log.close()


if __name__ == "__main__":
    sys.exit(main())
