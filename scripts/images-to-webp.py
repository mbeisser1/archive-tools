#!/usr/bin/env python3
"""Batch resize and convert images to WebP."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.cli_common import add_io_args  # noqa: E402
from lib.io_paths import default_log_path, resolve_io  # noqa: E402
from lib.tsv_log import LogEntry, STATUS_DRY_RUN, STATUS_ERROR, STATUS_OK, TsvLog  # noqa: E402
from lib.webp_convert import (  # noqa: E402
    DEFAULT_MAX_DIMENSION,
    DEFAULT_WEBP_QUALITY,
    convert_to_webp,
    default_jobs,
    dest_webp_path,
    iter_source_images,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resize (if needed) and convert images to WebP beside sources or under -o.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  images-to-webp.py -i ./photos
      → photo.jpg becomes photo.webp (max 1024px, quality 80)

  images-to-webp.py -i ./photos --max-dimension 2048 --quality 90 -n
""",
    )
    add_io_args(parser)
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_WEBP_QUALITY,
        metavar="N",
        help=f"WebP quality 0-100 (default: {DEFAULT_WEBP_QUALITY})",
    )
    parser.add_argument(
        "--max-dimension",
        type=int,
        default=DEFAULT_MAX_DIMENSION,
        metavar="PX",
        help=f"Max width/height in pixels; larger images are scaled down (default: {DEFAULT_MAX_DIMENSION})",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        metavar="N",
        help=f"Parallel conversions (default: {default_jobs()})",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress per-file progress lines",
    )
    return parser


def collect_sources(plan) -> list[Path]:
    if plan.single_file:
        from lib.webp_convert import is_webp_source

        if is_webp_source(plan.input_path):
            return [plan.input_path]
        return []
    return iter_source_images(plan.input_root)


def map_status(raw: str) -> str:
    if raw == "dry_run":
        return STATUS_DRY_RUN
    if raw == "error":
        return STATUS_ERROR
    return STATUS_OK


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    plan = resolve_io(args.input, args.output)
    jobs = args.jobs if args.jobs is not None else default_jobs()
    verbose = not args.quiet

    log = TsvLog(
        tool="images-to-webp.py",
        input_path=plan.input_path,
        output_path=plan.output_root or plan.output_path,
        dry_run=args.dry_run,
        log_path=default_log_path(plan, args.log),
    )

    sources = collect_sources(plan)
    if args.list_only:
        for source in sources:
            dest = dest_webp_path(source, plan, force=args.force)
            print(f"convert\t{source}\t->\t{dest}")
        print(f"# {len(sources)} file(s)", file=sys.stderr)
        return 0

    if not sources:
        print("No matching image files found.")
        return 0

    if plan.mirror and plan.output_root and not args.dry_run:
        plan.output_root.mkdir(parents=True, exist_ok=True)

    def work(source: Path) -> tuple[Path, Path, str, str, int | None, int | None]:
        dest = dest_webp_path(source, plan, force=args.force)
        raw, message, bytes_in, bytes_out = convert_to_webp(
            source,
            dest,
            quality=args.quality,
            max_dim=args.max_dimension,
            dry_run=args.dry_run,
            verbose=verbose,
        )
        return source, dest, raw, message, bytes_in, bytes_out

    if jobs <= 1 or len(sources) == 1:
        results = [work(source) for source in sources]
    else:
        results = []
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(work, source): source for source in sources}
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda row: row[0].as_posix().casefold())

    for source, dest, raw, message, bytes_in, bytes_out in results:
        log.write(LogEntry(
            operation="webp",
            status=map_status(raw),
            source=source,
            dest=dest,
            action="convert",
            message=message,
            bytes_in=bytes_in,
            bytes_out=bytes_out,
        ))

    return log.close()


if __name__ == "__main__":
    sys.exit(main())
