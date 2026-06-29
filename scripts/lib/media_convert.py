"""Convert stored media blobs to canonical .jpg, .mp3, or .mp4 formats."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

from lib.media_metadata import copy_metadata

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]


def _load_sibling_lib(name: str) -> ModuleType:
    path = _SCRIPTS_DIR / "lib" / f"{name}.py"
    mod_name = f"_archive_tools_{name}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load archive-tools module: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


_vt = _load_sibling_lib("video_convert")
VideoProbe = _vt.VideoProbe
probe_video = _vt.probe_video

CANONICAL_IMAGE_EXT = ".jpg"
CANONICAL_AUDIO_EXT = ".mp3"
CANONICAL_VIDEO_EXT = ".mp4"

DEFAULT_JPEG_QUALITY = 98
DEFAULT_VIDEO_HEIGHT = 720  # 720p: 1280x720 landscape; 720x1280 portrait
DEFAULT_VIDEO_MAX_FPS = 30.0
DEFAULT_VIDEO_CRF = 28
DEFAULT_VIDEO_PRESET = "medium"
DEFAULT_VIDEO_AUDIO_BITRATE = "96k"

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


def media_kind(path: Path) -> str | None:
    """Return image, audio, video, or None for unknown extensions."""
    ext = path.suffix.lower()
    if ext in IMAGE_SOURCE_EXTS or ext == CANONICAL_IMAGE_EXT:
        return "image"
    if ext in AUDIO_SOURCE_EXTS or ext == CANONICAL_AUDIO_EXT:
        return "audio"
    if ext in VIDEO_SOURCE_EXTS or ext == CANONICAL_VIDEO_EXT:
        return "video"
    return None


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


def video_720p_scale_filter() -> str:
    """Scale to 720p: landscape height 720 (e.g. 1280x720); portrait width 720; no upscale."""
    h = DEFAULT_VIDEO_HEIGHT
    return (
        f"scale=w='if(gt(iw\\,ih)\\,-2\\,min(iw\\,{h}))'"
        f":h='if(gt(iw\\,ih)\\,min(ih\\,{h})\\,-2)'"
    )


def video_fps_filter(
    probe: VideoProbe | None,
    max_fps: float = DEFAULT_VIDEO_MAX_FPS,
) -> str | None:
    """Cap frame rate only when source exceeds max_fps."""
    if probe and probe.fps is not None and probe.fps > max_fps:
        return f"fps={max_fps}"
    return None


def video_filter_chain(
    probe: VideoProbe | None = None,
    max_fps: float = DEFAULT_VIDEO_MAX_FPS,
) -> str:
    parts = [video_720p_scale_filter()]
    fps = video_fps_filter(probe, max_fps)
    if fps:
        parts.append(fps)
    return ",".join(parts)


def is_video_at_720p_or_below(probe: VideoProbe) -> bool:
    if probe.width <= 0 or probe.height <= 0:
        return False
    h = DEFAULT_VIDEO_HEIGHT
    if probe.width >= probe.height:
        return probe.height <= h
    return probe.width <= h


def should_skip_video_reencode(
    source: Path,
    probe: VideoProbe | None,
    *,
    skip_inefficient: bool,
) -> bool:
    """True when an MP4 is already H.264 at 720p with fps <= max (re-encode wasteful)."""
    if not skip_inefficient:
        return False
    if source.suffix.lower() != CANONICAL_VIDEO_EXT:
        return False
    if probe is None:
        return False
    if probe.codec not in ("h264", "avc1"):
        return False
    if not is_video_at_720p_or_below(probe):
        return False
    if probe.fps is not None and probe.fps > DEFAULT_VIDEO_MAX_FPS + 0.01:
        return False
    return True


def ffmpeg_mp4_reencode_cmd(
    source: Path,
    dest: Path,
    probe: VideoProbe | None,
) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map_metadata",
        "0",
        "-vf",
        video_filter_chain(probe),
        "-c:v",
        "libx264",
        "-crf",
        str(DEFAULT_VIDEO_CRF),
        "-preset",
        DEFAULT_VIDEO_PRESET,
        "-c:a",
        "aac",
        "-b:a",
        DEFAULT_VIDEO_AUDIO_BITRATE,
        "-movflags",
        "+use_metadata_tags",
        str(dest),
    ]


def reencode_mp4_video(
    source: Path,
    *,
    skip_inefficient: bool = True,
) -> tuple[Path | None, bool]:
    """Re-encode MP4 to 720p H.264. Returns (temp_path, skipped_intentionally)."""
    probe = probe_video(source)
    if should_skip_video_reencode(source, probe, skip_inefficient=skip_inefficient):
        return None, True
    if not _ffmpeg_available():
        return None, False
    tmp = temp_output_path(CANONICAL_VIDEO_EXT)
    try:
        subprocess.run(
            ffmpeg_mp4_reencode_cmd(source, tmp, probe),
            check=True,
            capture_output=True,
        )
        if tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            return None, False
        copy_metadata(source, tmp)
        return tmp, False
    except subprocess.CalledProcessError:
        tmp.unlink(missing_ok=True)
        return None, False


# Backward-compatible alias (720p scale, no fps cap without probe)
def video_scale_filter(max_dimension: int = DEFAULT_VIDEO_HEIGHT) -> str:
    del max_dimension  # 720p uses height/width semantics, not long-edge cap
    return video_720p_scale_filter()


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
            probe = probe_video(source)
            cmd = ffmpeg_mp4_reencode_cmd(source, tmp, probe)
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
