#!/usr/bin/env python3
"""Convert images to JPEG with metadata preserved."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.cli_common import add_io_args  # noqa: E402
from lib.image_convert import (  # noqa: E402
    collect_candidates,
    convert_image,
    copy_jpeg,
    copy_takeout_sidecar,
    dest_jpg_path,
    resolve_extensions,
)
from lib.io_paths import default_log_path, resolve_io  # noqa: E402
from lib.media_convert import DEFAULT_JPEG_QUALITY  # noqa: E402
from lib.media_metadata import warn_if_missing  # noqa: E402
from lib.tsv_log import LogEntry, STATUS_DRY_RUN, STATUS_ERROR, STATUS_OK, STATUS_SKIP, TsvLog  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert images to JPEG with metadata (exiftool).",
    )
    add_io_args(parser)
    parser.add_argument(
        "--all-images",
        action="store_true",
        help="Convert all supported non-JPEG images, not just HEIC/PNG",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=DEFAULT_JPEG_QUALITY,
        metavar="N",
        help=f"JPEG quality 1-100 (default: {DEFAULT_JPEG_QUALITY})",
    )
    parser.add_argument(
        "--takeout-sidecars",
        action="store_true",
        help="Copy Google Takeout supplemental-metadata.json sidecars to match output JPEG names",
    )
    parser.add_argument(
        "--no-copy-jpeg",
        action="store_true",
        help="When mirroring to -o, do not copy existing JPEG files",
    )
    return parser


def map_status(raw: str) -> str:
    if raw == "dry_run":
        return STATUS_DRY_RUN
    if raw == "skip":
        return STATUS_SKIP
    if raw == "error":
        return STATUS_ERROR
    return STATUS_OK


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    warn_if_missing()
    plan = resolve_io(args.input, args.output)
    extensions = resolve_extensions(args.all_images)
    log = TsvLog(
        tool="images-to-jpg.py",
        input_path=plan.input_path,
        output_path=plan.output_root or plan.output_path,
        dry_run=args.dry_run,
        log_path=default_log_path(plan, args.log),
    )

    items = collect_candidates(
        plan,
        extensions,
        copy_existing_jpeg=not args.no_copy_jpeg and plan.mirror,
    )

    if args.list_only:
        for source, action in items:
            dest = dest_jpg_path(source, plan)
            print(f"{action}\t{source}\t->\t{dest}")
        print(f"# {len(items)} file(s)", file=sys.stderr)
        return 0

    if not items:
        print("No matching image files found.")
        return 0

    if plan.mirror and plan.output_root and not args.dry_run:
        plan.output_root.mkdir(parents=True, exist_ok=True)

    for source, action in items:
        dest = dest_jpg_path(source, plan)
        if action == "convert":
            raw, message, bytes_in, bytes_out = convert_image(
                source,
                dest,
                dry_run=args.dry_run,
                force=args.force,
                jpeg_quality=args.jpeg_quality,
            )
        else:
            raw, message, bytes_in, bytes_out = copy_jpeg(
                source,
                dest,
                dry_run=args.dry_run,
                force=args.force,
            )

        if raw in ("ok", "dry_run") and args.takeout_sidecars:
            copy_takeout_sidecar(source, dest, dry_run=args.dry_run)

        log.write(LogEntry(
            operation="image",
            status=map_status(raw),
            source=source,
            dest=dest,
            action=action,
            message=message,
            bytes_in=bytes_in,
            bytes_out=bytes_out,
        ))

    return log.close()


if __name__ == "__main__":
    sys.exit(main())
