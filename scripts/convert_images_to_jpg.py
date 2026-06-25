#!/usr/bin/env python3
"""Convert HEIC, PNG, and other images to JPEG with metadata preserved."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.media_convert import (  # noqa: E402
    CANONICAL_IMAGE_EXT,
    DEFAULT_JPEG_QUALITY,
    convert_media,
    target_extension,
)
from lib.media_metadata import warn_if_missing  # noqa: E402

DEFAULT_EXTENSIONS = frozenset({".heic", ".heics", ".png"})


def is_convertible(path: Path, extensions: frozenset[str]) -> bool:
    if path.suffix.casefold() not in extensions:
        return False
    return target_extension(path) == CANONICAL_IMAGE_EXT


def iter_image_files(root: Path, extensions: frozenset[str]) -> list[Path]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and is_convertible(path, extensions)
    ]
    files.sort(key=lambda p: p.as_posix().casefold())
    return files


def output_path_for(source: Path, input_root: Path, output_root: Path | None) -> Path:
    if output_root is None:
        return source.with_suffix(CANONICAL_IMAGE_EXT)
    try:
        rel = source.resolve().relative_to(input_root.resolve())
    except ValueError:
        rel = Path(source.name)
    return output_root / rel.with_suffix(CANONICAL_IMAGE_EXT)


def convert_one(
    source: Path,
    dest: Path,
    *,
    dry_run: bool,
    force: bool,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> tuple[str, str]:
    if dest.is_file() and not force:
        return "skip", "output already exists"

    if dry_run:
        return "ok", "dry-run"

    converted = convert_media(source, CANONICAL_IMAGE_EXT, jpeg_quality=jpeg_quality)
    if converted is None:
        return "error", "conversion failed (need ffmpeg or ImageMagick, plus exiftool for metadata)"

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(converted), str(dest))
    return "ok", ""


def log_line(source: Path, dest: Path, status: str, message: str = "") -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    if status == "skip":
        return f"{ts} SKIP {source} -> {dest} ({message})"
    if status == "error":
        return f"{ts} ERROR {source} -> {dest}: {message}"
    if message == "dry-run":
        return f"{ts} DRY-RUN {source} -> {dest}"
    return f"{ts} OK {source} -> {dest}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert HEIC, PNG, and other images to JPEG with metadata (exiftool)."
        ),
    )
    parser.add_argument(
        "-i",
        "--input-dir",
        type=Path,
        required=True,
        help="Directory to scan recursively",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Output root (default: write .jpg beside each source file)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Convert a single image (still uses --input-dir for output layout)",
    )
    parser.add_argument(
        "--all-images",
        action="store_true",
        help="Convert all supported non-JPEG images (webp, gif, tiff, …), not just HEIC/PNG",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=DEFAULT_JPEG_QUALITY,
        metavar="N",
        help="JPEG output quality 1-100 (default: 98)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .jpg outputs",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="List matching paths and exit",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show planned conversions without writing",
    )
    return parser


def resolve_extensions(args: argparse.Namespace) -> frozenset[str]:
    if args.all_images:
        from lib.media_convert import IMAGE_SOURCE_EXTS

        return frozenset(ext.casefold() for ext in IMAGE_SOURCE_EXTS)
    return DEFAULT_EXTENSIONS


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    warn_if_missing()
    extensions = resolve_extensions(args)

    input_dir = args.input_dir.resolve()
    if not input_dir.is_dir():
        print(f"ERROR: input directory not found: {input_dir}", file=sys.stderr)
        return 1

    output_dir = args.output_dir.resolve() if args.output_dir else None

    if args.file:
        source = args.file.resolve()
        if not source.is_file():
            print(f"ERROR: file not found: {source}", file=sys.stderr)
            return 1
        if not is_convertible(source, extensions):
            exts = ", ".join(sorted(extensions))
            print(f"ERROR: not a convertible image ({exts}): {source}", file=sys.stderr)
            return 1
        candidates = [source]
    else:
        candidates = iter_image_files(input_dir, extensions)

    if args.list_only:
        for path in candidates:
            print(path)
        print(f"# {len(candidates)} file(s)", file=sys.stderr)
        return 0

    if not candidates:
        print("No matching image files found.")
        return 0

    if output_dir and not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    ok = skipped = errors = dry = 0
    for source in candidates:
        dest = output_path_for(source, input_dir, output_dir)
        status, message = convert_one(
            source, dest, dry_run=args.dry_run, force=args.force, jpeg_quality=args.jpeg_quality
        )
        print(log_line(source, dest, status, message))
        if status == "ok" and message != "dry-run":
            ok += 1
        elif status == "ok" and message == "dry-run":
            dry += 1
        elif status == "skip":
            skipped += 1
        else:
            errors += 1

    print(
        f"\nDone: {ok} converted, {skipped} skipped, {errors} error(s), {dry} dry-run",
        file=sys.stderr,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
