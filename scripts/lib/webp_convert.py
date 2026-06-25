"""Image → WebP conversion with optional resize (cwebp / gif2webp / ImageMagick)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from lib.io_paths import IoPlan, dest_with_suffix

WEBP_SUFFIX = ".webp"
DEFAULT_WEBP_QUALITY = 80
DEFAULT_MAX_DIMENSION = 1024

WEBP_SOURCE_EXTS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
    }
)


def default_jobs() -> int:
    return os.cpu_count() or 4


def clamp_quality(quality: int) -> int:
    return max(0, min(100, quality))


def clamp_max_dimension(max_dim: int) -> int:
    return max(1, max_dim)


def is_webp_source(path: Path) -> bool:
    return path.suffix.casefold() in WEBP_SOURCE_EXTS


def iter_source_images(root: Path) -> list[Path]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and is_webp_source(path)
    ]
    files.sort(key=lambda p: p.as_posix().casefold())
    return files


def _magick_command() -> list[str] | None:
    if shutil.which("magick"):
        return ["magick"]
    if shutil.which("convert"):
        return ["convert"]
    return None


def image_dimensions(path: Path) -> tuple[int, int] | None:
    if shutil.which("identify"):
        cmd = ["identify", "-format", "%w %h", str(path)]
    else:
        magick = _magick_command()
        if magick is None:
            return None
        cmd = [*magick, "identify", "-format", "%w %h", str(path)]

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None

    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def needs_resize(width: int, height: int, max_dim: int) -> bool:
    return width > max_dim or height > max_dim


def dest_webp_path(source: Path, plan: IoPlan, *, force: bool) -> Path:
    """Map source to a .webp path; use stem_N.webp when the base name is taken."""
    if plan.single_file and plan.output_path is not None:
        dest = plan.output_path
        if dest.suffix.casefold() != WEBP_SUFFIX:
            dest = dest.with_suffix(WEBP_SUFFIX)
        return dest

    candidate = dest_with_suffix(source, plan, suffix=WEBP_SUFFIX)
    if force or not candidate.exists():
        return candidate

    parent = candidate.parent
    stem = source.stem
    suffix = 1
    while (parent / f"{stem}_{suffix}{WEBP_SUFFIX}").exists():
        suffix += 1
    return parent / f"{stem}_{suffix}{WEBP_SUFFIX}"


def _run_quiet(cmd: list[str]) -> bool:
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _convert_with_magick(
    source: Path,
    dest: Path,
    *,
    quality: int,
    max_dim: int,
    resize: bool,
    gif: bool,
) -> bool:
    magick = _magick_command()
    if magick is None:
        return False

    args = [str(source)]
    if gif:
        args = ["-coalesce", *args]
    if resize:
        args.extend(["-resize", f"{max_dim}x{max_dim}>"])
    args.extend(["-quality", str(quality), str(dest)])
    return _run_quiet([*magick, *args]) and dest.is_file()


def _convert_gif(
    source: Path,
    dest: Path,
    *,
    quality: int,
    max_dim: int,
    resize: bool,
) -> bool:
    if shutil.which("gif2webp"):
        cmd = ["gif2webp", "-q", str(quality)]
        if resize:
            cmd.extend(["-resize", str(max_dim), "0"])
        cmd.extend([str(source), "-o", str(dest)])
        if _run_quiet(cmd):
            return dest.is_file()
        print(f"WARN: gif2webp failed for {source}; falling back to convert.")
    return _convert_with_magick(
        source,
        dest,
        quality=quality,
        max_dim=max_dim,
        resize=resize,
        gif=True,
    )


def _convert_static(
    source: Path,
    dest: Path,
    *,
    quality: int,
    max_dim: int,
    resize: bool,
) -> bool:
    resized_tmp: Path | None = None
    try:
        if resize and shutil.which("cwebp"):
            magick = _magick_command()
            if magick is not None:
                resized_tmp = source.with_suffix(f".resized.{os.getpid()}{source.suffix}")
                if not _run_quiet(
                    [*magick, str(source), "-resize", f"{max_dim}x{max_dim}>", str(resized_tmp)]
                ):
                    print(
                        f"WARN: convert resize failed for {source}; trying cwebp directly."
                    )
                    resized_tmp.unlink(missing_ok=True)
                    resized_tmp = None
                elif resized_tmp.is_file():
                    if _run_quiet(
                        ["cwebp", "-q", str(quality), str(resized_tmp), "-o", str(dest)]
                    ):
                        return dest.is_file()
                    if _convert_with_magick(
                        resized_tmp,
                        dest,
                        quality=quality,
                        max_dim=max_dim,
                        resize=False,
                        gif=False,
                    ):
                        return True

        if shutil.which("cwebp"):
            if _run_quiet(["cwebp", "-q", str(quality), str(source), "-o", str(dest)]):
                return dest.is_file()
            if _convert_with_magick(
                source,
                dest,
                quality=quality,
                max_dim=max_dim,
                resize=resize,
                gif=False,
            ):
                return True
        elif _convert_with_magick(
            source,
            dest,
            quality=quality,
            max_dim=max_dim,
            resize=resize,
            gif=False,
        ):
            return True
        return False
    finally:
        if resized_tmp is not None:
            resized_tmp.unlink(missing_ok=True)


def convert_to_webp(
    source: Path,
    dest: Path,
    *,
    quality: int = DEFAULT_WEBP_QUALITY,
    max_dim: int = DEFAULT_MAX_DIMENSION,
    dry_run: bool = False,
    verbose: bool = True,
) -> tuple[str, str, int | None, int | None]:
    """Convert source image to WebP at dest. Returns status, message, bytes_in, bytes_out."""
    quality = clamp_quality(quality)
    max_dim = clamp_max_dimension(max_dim)

    try:
        bytes_in = source.stat().st_size
    except OSError as exc:
        return "error", str(exc), None, None

    dims = image_dimensions(source)
    resize = False
    if dims is not None:
        resize = needs_resize(dims[0], dims[1], max_dim)
        width, height = dims
    else:
        width, height = "?", "?"

    if verbose:
        print(
            f"PROCESS: {source} -> {dest} "
            f"(w={width} h={height} resize={int(resize)})"
        )

    if dry_run:
        return "dry_run", "", bytes_in, None

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(f"{dest.suffix}.tmp.{os.getpid()}")

    try:
        is_gif = source.suffix.casefold() == ".gif"
        ok = (
            _convert_gif(source, tmp, quality=quality, max_dim=max_dim, resize=resize)
            if is_gif
            else _convert_static(source, tmp, quality=quality, max_dim=max_dim, resize=resize)
        )

        if not ok and shutil.which("cwebp") and not is_gif:
            ok = _run_quiet(["cwebp", "-q", str(quality), str(source), "-o", str(tmp)])

        if ok and tmp.is_file():
            tmp.replace(dest)
            bytes_out = dest.stat().st_size
            if verbose:
                print(f"OK: {dest}")
            return "ok", "", bytes_in, bytes_out

        print(f"FAILED: conversion failed for {source}", file=sys.stderr)
        return "error", "conversion failed", bytes_in, None
    finally:
        tmp.unlink(missing_ok=True)
