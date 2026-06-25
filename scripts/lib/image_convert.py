"""Image → JPEG conversion helpers."""

from __future__ import annotations

import shutil
from pathlib import Path

from lib.io_paths import IoPlan, dest_with_suffix, relative_to_root
from lib.media_convert import (
    CANONICAL_IMAGE_EXT,
    DEFAULT_JPEG_QUALITY,
    IMAGE_SOURCE_EXTS,
    convert_media,
    target_extension,
)

DEFAULT_EXTENSIONS = frozenset({".heic", ".heics", ".png"})
JPEG_EXTENSIONS = frozenset({".jpg", ".jpeg"})


def resolve_extensions(all_images: bool) -> frozenset[str]:
    if all_images:
        return frozenset(ext.casefold() for ext in IMAGE_SOURCE_EXTS if ext not in JPEG_EXTENSIONS)
    return DEFAULT_EXTENSIONS


def is_convertible(path: Path, extensions: frozenset[str]) -> bool:
    if path.suffix.casefold() not in extensions:
        return False
    return target_extension(path) == CANONICAL_IMAGE_EXT


def is_jpeg(path: Path) -> bool:
    return path.suffix.casefold() in JPEG_EXTENSIONS


def iter_convertible_images(root: Path, extensions: frozenset[str]) -> list[Path]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and is_convertible(path, extensions)
    ]
    files.sort(key=lambda p: p.as_posix().casefold())
    return files


def iter_jpeg_files(root: Path) -> list[Path]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and is_jpeg(path)
    ]
    files.sort(key=lambda p: p.as_posix().casefold())
    return files


def dest_jpg_path(source: Path, plan: IoPlan) -> Path:
    return dest_with_suffix(source, plan, suffix=CANONICAL_IMAGE_EXT)


def convert_image(
    source: Path,
    dest: Path,
    *,
    dry_run: bool,
    force: bool,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> tuple[str, str, int | None, int | None]:
    try:
        bytes_in = source.stat().st_size
    except OSError as exc:
        return "error", str(exc), None, None

    if dest.is_file() and not force:
        return "skip", "output already exists", bytes_in, dest.stat().st_size

    if dry_run:
        return "dry_run", "", bytes_in, None

    converted = convert_media(source, CANONICAL_IMAGE_EXT, jpeg_quality=jpeg_quality)
    if converted is None:
        return "error", "conversion failed", bytes_in, None

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(converted), str(dest))
    return "ok", "", bytes_in, dest.stat().st_size


def copy_jpeg(
    source: Path,
    dest: Path,
    *,
    dry_run: bool,
    force: bool,
) -> tuple[str, str, int | None, int | None]:
    try:
        bytes_in = source.stat().st_size
    except OSError as exc:
        return "error", str(exc), None, None

    if dest.is_file() and not force:
        return "skip", "output already exists", bytes_in, dest.stat().st_size

    if dry_run:
        return "dry_run", "", bytes_in, None

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return "ok", "", bytes_in, dest.stat().st_size


def find_takeout_sidecar(source: Path) -> Path | None:
    direct = Path(f"{source}.supplemental-metadata.json")
    if direct.is_file():
        return direct
    parent = source.parent
    name = source.name
    for candidate in parent.iterdir():
        if candidate.is_file() and candidate.name.lower() == f"{name.lower()}.supplemental-metadata.json":
            return candidate
    return None


def jpeg_ext_for_source(source: Path) -> str:
    base = source.name
    stem, dot, ext = base.rpartition(".")
    if not dot:
        return "jpg"
    if ext == ext.upper():
        return "JPG"
    if ext == ext.lower():
        return "jpg"
    return "Jpg"


def copy_takeout_sidecar(source: Path, dest_jpg: Path, *, dry_run: bool) -> None:
    sidecar = find_takeout_sidecar(source)
    if sidecar is None:
        return
    dest_sidecar = Path(f"{dest_jpg}.supplemental-metadata.json")
    if dry_run:
        return
    dest_sidecar.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sidecar, dest_sidecar)


def collect_candidates(
    plan: IoPlan,
    extensions: frozenset[str],
    *,
    copy_existing_jpeg: bool,
) -> list[tuple[Path, str]]:
    if plan.single_file:
        if is_convertible(plan.input_path, extensions):
            return [(plan.input_path, "convert")]
        if copy_existing_jpeg and is_jpeg(plan.input_path):
            return [(plan.input_path, "copy_jpeg")]
        return []

    items: list[tuple[Path, str]] = [
        (path, "convert") for path in iter_convertible_images(plan.input_root, extensions)
    ]
    if copy_existing_jpeg:
        items.extend((path, "copy_jpeg") for path in iter_jpeg_files(plan.input_root))
    return items
