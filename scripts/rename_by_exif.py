#!/usr/bin/env python3
"""Rename media files from EXIF capture time."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DATE_TAGS = ("DateTimeOriginal", "CreateDate", "ModifyDate")

EXIF_FORMATS = (
    "%Y:%m:%d %H:%M:%S",
    "%Y:%m:%d %H:%M",
    "%Y:%m:%d",
)

EXTENSIONS = frozenset({
    "jpg", "jpeg", "png", "tif", "tiff", "heic", "heif", "webp", "gif",
    "mp4", "mov", "avi", "mkv", "m4v", "mpg", "mpeg", "3gp",
})


def require_exiftool() -> str:
    exiftool = shutil.which("exiftool")
    if not exiftool:
        print(
            "ERROR: exiftool not found on PATH "
            "(install ExifTool or https://exiftool.org/install.html)",
            file=sys.stderr,
        )
        sys.exit(1)
    return exiftool


def read_exif_raw(exiftool: str, path: Path, tag: str) -> str | None:
    result = subprocess.run(
        [exiftool, "-s3", f"-{tag}", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw or raw == "-":
        return None
    return raw


def parse_exif_datetime(raw: str) -> datetime | None:
    raw = raw.strip()
    for fmt in EXIF_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            if fmt == "%Y:%m:%d":
                return dt.replace(hour=0, minute=0, second=0)
            if fmt == "%Y:%m:%d %H:%M":
                return dt.replace(second=0)
            return dt
        except ValueError:
            continue
    return None


def read_capture_datetime(exiftool: str, path: Path, debug: bool) -> datetime | None:
    for tag in DATE_TAGS:
        raw = read_exif_raw(exiftool, path, tag)
        if raw is None:
            continue
        if debug:
            print(f"DEBUG: {path} {tag} raw=[{raw}]", file=sys.stderr)
        dt = parse_exif_datetime(raw)
        if dt is not None:
            if debug:
                print(f"DEBUG: {path} parsed=[{format_stem(dt)}]", file=sys.stderr)
            return dt
    return None


def format_stem(dt: datetime) -> str:
    return f"{dt:%Y-%m-%d}__{dt:%H-%M-%S}"


def build_name_suffix_style(suffix: str, dt: datetime, ext: str) -> str:
    return f"{format_stem(dt)}-{suffix}.{ext.lower()}"


def build_name_prefix_style(prefix: str, dt: datetime, ext: str) -> str:
    return f"{prefix}-{format_stem(dt)}.{ext.lower()}"


def slot_key_suffix_style(suffix: str, dt: datetime) -> str:
    return f"{format_stem(dt)}-{suffix}"


def slot_key_prefix_style(dt: datetime) -> str:
    return format_stem(dt)


def slot_taken(slot: str, directory: Path, claimed_slots: set[str]) -> bool:
    if slot in claimed_slots:
        return True
    prefix = slot + "."
    return any(
        path.is_file() and path.name.startswith(prefix)
        for path in directory.iterdir()
    )


def next_available_name_suffix(
    suffix: str,
    dt: datetime,
    ext: str,
    directory: Path,
    claimed: set[str],
    claimed_slots: set[str],
) -> str:
    for bump in range(60):
        new_second = dt.second + bump
        if new_second > 59:
            break
        candidate_dt = dt.replace(second=new_second)
        slot = slot_key_suffix_style(suffix, candidate_dt)
        if slot_taken(slot, directory, claimed_slots):
            continue
        name = build_name_suffix_style(suffix, candidate_dt, ext)
        if name in claimed:
            continue
        if (directory / name).exists():
            continue
        claimed.add(name)
        claimed_slots.add(slot)
        return name
    raise RuntimeError(
        f"Too many collisions for {format_stem(dt)} in {directory}"
    )


def next_available_name_prefix(
    prefix: str,
    dt: datetime,
    ext: str,
    directory: Path,
    claimed: set[str],
    claimed_slots: set[str],
) -> str:
    for bump in range(60):
        new_second = dt.second + bump
        if new_second > 59:
            break
        candidate_dt = dt.replace(second=new_second)
        slot = slot_key_prefix_style(candidate_dt)
        if slot_taken(slot, directory, claimed_slots):
            continue
        name = build_name_prefix_style(prefix, candidate_dt, ext)
        if name in claimed:
            continue
        if (directory / name).exists():
            continue
        claimed.add(name)
        claimed_slots.add(slot)
        return name
    raise RuntimeError(
        f"Too many collisions for {format_stem(dt)} in {directory}"
    )


def iter_media_files(directory: Path):
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        ext = path.suffix.lstrip(".").lower()
        if ext in EXTENSIONS:
            yield path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rename files from EXIF capture time.",
        epilog=(
            "Default format: YYYY-mm-DD__HH-MM-SS-{SUFFIX}.{ext}\n"
            "With --prefix:  {PREFIX}-YYYY-mm-DD__HH-MM-SS.{ext}\n"
            "Duplicate timestamps bump the seconds field (00, 01, 02, ...)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "label",
        nargs="?",
        default="",
        help="Suffix (default mode) or prefix when --prefix is set",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=Path("."),
        help="Directory to scan (default: .)",
    )
    parser.add_argument(
        "--prefix",
        action="store_true",
        help="Treat label as prefix: {PREFIX}-YYYY-mm-DD__HH-MM-SS.ext",
    )
    parser.add_argument(
        "--execute", "-x",
        action="store_true",
        help="Apply renames (default is dry run)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show raw EXIF values and parsed datetime",
    )
    args = parser.parse_args()

    label = args.label
    directory = args.directory.resolve()
    if not label:
        parser.error("label is required (suffix or prefix)")
    if not directory.is_dir():
        print(f"ERROR: Not a directory: {directory}", file=sys.stderr)
        sys.exit(1)

    exiftool = require_exiftool()

    if args.prefix:
        already_pattern = re.compile(
            rf"^{re.escape(label)}-\d{{4}}-\d{{2}}-\d{{2}}__\d{{2}}-\d{{2}}-\d{{2}}\.",
            re.IGNORECASE,
        )
    else:
        already_pattern = re.compile(
            rf"^\d{{4}}-\d{{2}}-\d{{2}}__\d{{2}}-\d{{2}}-\d{{2}}-{re.escape(label)}\.",
            re.IGNORECASE,
        )

    claimed: set[str] = set()
    claimed_slots: set[str] = set()
    renamed = 0
    skipped = 0

    for path in iter_media_files(directory):
        base = path.name
        if already_pattern.match(base):
            print(f"SKIP (already renamed): {base}")
            skipped += 1
            continue

        dt = read_capture_datetime(exiftool, path, args.debug)
        if dt is None:
            print(f"SKIP (no EXIF date): {base}")
            skipped += 1
            continue

        ext = path.suffix.lstrip(".")
        if args.prefix:
            new_name = next_available_name_prefix(
                label, dt, ext, directory, claimed, claimed_slots,
            )
        else:
            new_name = next_available_name_suffix(
                label, dt, ext, directory, claimed, claimed_slots,
            )

        if base == new_name:
            print(f"OK (unchanged): {base}")
            continue

        target = directory / new_name
        if args.execute:
            path.rename(target)
            print(f"RENAMED: {base} -> {new_name}")
        else:
            print(f"WOULD RENAME: {base} -> {new_name}")
        renamed += 1

    print()
    if args.execute:
        print(f"Done. Renamed: {renamed}, skipped: {skipped}")
    else:
        print(f"Dry run. Would rename: {renamed}, skipped: {skipped}")
        print("Re-run with --execute to apply.")


if __name__ == "__main__":
    main()
