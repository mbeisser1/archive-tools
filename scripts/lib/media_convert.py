"""Convert stored media blobs to canonical .jpg, .mp3, or .mp4 formats."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from lib.media_metadata import copy_metadata

CANONICAL_IMAGE_EXT = ".jpg"
CANONICAL_AUDIO_EXT = ".mp3"
CANONICAL_VIDEO_EXT = ".mp4"

DEFAULT_JPEG_QUALITY = 98

CANONICAL_EXTS = frozenset(
    {CANONICAL_IMAGE_EXT, CANONICAL_AUDIO_EXT, CANONICAL_VIDEO_EXT}
)

IMAGE_SOURCE_EXTS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".heic",
        ".heics",
        ".bmp",
        ".tif",
        ".tiff",
    }
)
HEIC_EXTENSIONS = frozenset({".heic", ".heics"})
AUDIO_SOURCE_EXTS = frozenset(
    {
        ".caf",
        ".amr",
        ".m4a",
        ".aac",
        ".mp3",
        ".wav",
        ".ogg",
    }
)
VIDEO_SOURCE_EXTS = frozenset(
    {
        ".mp4",
        ".mov",
        ".3gp",
        ".3gpp",
        ".m4v",
        ".webm",
        ".mpeg",
        ".mpg",
        ".mkv",
    }
)

MIME_FOR_EXT = {
    CANONICAL_IMAGE_EXT: "image/jpeg",
    CANONICAL_AUDIO_EXT: "audio/mpeg",
    CANONICAL_VIDEO_EXT: "video/mp4",
}


def target_extension(path: Path) -> str | None:
    """Return canonical output extension, or None if already canonical."""
    ext = path.suffix.lower()
    if ext in CANONICAL_EXTS:
        return None
    if ext in IMAGE_SOURCE_EXTS:
        return CANONICAL_IMAGE_EXT
    if ext in AUDIO_SOURCE_EXTS:
        return CANONICAL_AUDIO_EXT
    if ext in VIDEO_SOURCE_EXTS:
        return CANONICAL_VIDEO_EXT
    return None


def mime_for_extension(ext: str) -> str:
    ext = ext if ext.startswith(".") else f".{ext}"
    return MIME_FOR_EXT.get(ext.lower(), "application/octet-stream")


def temp_output_path(suffix: str) -> Path:
    """Create an empty temp file path, closing mkstemp's fd immediately."""
    fd, name = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return Path(name)


def _magick_command() -> list[str] | None:
    if shutil.which("magick"):
        return ["magick"]
    if shutil.which("convert"):
        return ["convert"]
    return None


def clamp_jpeg_quality(quality: int) -> int:
    return max(1, min(100, quality))


def ffmpeg_mjpeg_qv(jpeg_quality: int) -> int:
    """Map JPEG quality 1-100 to ffmpeg mjpeg q:v (1=best, 31=worst)."""
    q = clamp_jpeg_quality(jpeg_quality)
    if q >= 98:
        return 1
    if q >= 95:
        return 2
    if q >= 92:
        return 3
    if q >= 88:
        return 4
    return max(2, min(31, round(1 + (100 - q) * 0.15)))


def _magick_source_arg(source: Path) -> str:
    """First frame for animated images; full image otherwise."""
    if source.suffix.lower() in {".webp", ".gif"}:
        return f"{source}[0]"
    return str(source)


def _is_heic(source: Path) -> bool:
    return source.suffix.casefold() in HEIC_EXTENSIONS


def _convert_image_heif_convert(source: Path, dest: Path, *, jpeg_quality: int) -> bool:
    if not shutil.which("heif-convert"):
        return False
    quality = clamp_jpeg_quality(jpeg_quality)
    try:
        subprocess.run(
            ["heif-convert", "-q", str(quality), str(source), str(dest)],
            check=True,
            capture_output=True,
        )
        return dest.is_file() and dest.stat().st_size > 0
    except subprocess.CalledProcessError:
        return False


def _convert_image_magick(source: Path, dest: Path, *, jpeg_quality: int) -> bool:
    cmd = _magick_command()
    if cmd is None:
        return False
    quality = clamp_jpeg_quality(jpeg_quality)
    args = [_magick_source_arg(source), "-auto-orient", "-quality", str(quality), str(dest)]
    try:
        subprocess.run(
            [*cmd, *args],
            check=True,
            capture_output=True,
        )
        return dest.is_file() and dest.stat().st_size > 0
    except subprocess.CalledProcessError:
        return False


def _convert_image_ffmpeg(source: Path, dest: Path, *, jpeg_quality: int) -> bool:
    qv = ffmpeg_mjpeg_qv(jpeg_quality)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-map_metadata",
                "0",
                "-frames:v",
                "1",
                "-q:v",
                str(qv),
                str(dest),
            ],
            check=True,
            capture_output=True,
        )
        return dest.is_file() and dest.stat().st_size > 0
    except subprocess.CalledProcessError:
        return False


def _image_to_jpeg_converters(source: Path) -> list:
    """Return image converters in priority order (HEIC: libheif-friendly tools first)."""
    if _is_heic(source):
        return [_convert_image_magick, _convert_image_heif_convert, _convert_image_ffmpeg]
    if _ffmpeg_available():
        return [_convert_image_ffmpeg, _convert_image_magick]
    return [_convert_image_magick]


def _convert_image_to_jpeg(
    source: Path, dest: Path, *, jpeg_quality: int
) -> bool:
    for convert in _image_to_jpeg_converters(source):
        if convert(source, dest, jpeg_quality=jpeg_quality):
            return True
    return False


def convert_media(
    source: Path,
    target_ext: str,
    *,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> Path | None:
    """Convert source to target_ext inside a temp file; caller must delete temp."""
    suffix = target_ext if target_ext.startswith(".") else f".{target_ext}"
    tmp = temp_output_path(suffix)

    if suffix == CANONICAL_IMAGE_EXT:
        try:
            if _convert_image_to_jpeg(source, tmp, jpeg_quality=jpeg_quality):
                copy_metadata(source, tmp)
                return tmp
            tmp.unlink(missing_ok=True)
            return None
        except OSError:
            tmp.unlink(missing_ok=True)
            return None

    if not _ffmpeg_available():
        tmp.unlink(missing_ok=True)
        return None

    try:
        if suffix == CANONICAL_AUDIO_EXT:
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-map_metadata",
                "0",
                "-vn",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "4",
                str(tmp),
            ]
        else:
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-map_metadata",
                "0",
                "-c:v",
                "libx264",
                "-crf",
                "28",
                "-preset",
                "veryslow",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+use_metadata_tags",
                str(tmp),
            ]
        subprocess.run(cmd, check=True, capture_output=True)
        if tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            return None
        copy_metadata(source, tmp)
        return tmp
    except subprocess.CalledProcessError:
        tmp.unlink(missing_ok=True)
        return None


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
