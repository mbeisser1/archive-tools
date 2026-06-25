"""Video probe, encode, and remux for MP4 archival output."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

VIDEO_EXTENSIONS = frozenset(
    {
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".m4v",
        ".mts",
        ".wmv",
        ".flv",
        ".webm",
        ".3gp",
        ".mpg",
        ".mpeg",
        ".m2ts",
        ".vob",
        ".ogv",
        ".ts",
    }
)

_SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([KMGTP])?B?$", re.IGNORECASE)
_SIZE_UNITS = {
    "K": 1024,
    "M": 1024**2,
    "G": 1024**3,
    "T": 1024**4,
    "P": 1024**5,
}

CANONICAL_VIDEO_EXT = ".mp4"
ABOVE_720P_LONG_EDGE = 1281   # above 1280x720
ABOVE_1080P_LONG_EDGE = 1921  # above 1920x1080
UHD_4K_LONG_EDGE = 3840


@dataclass
class VideoProbe:
    codec: str
    width: int
    height: int
    bitrate: int | None  # bits/s
    duration: float | None
    fps: float | None = None


@dataclass
class ScanCriteria:
    """AND filters for discovering candidate files."""

    min_bytes: int = 0
    min_long_edge: int | None = None  # e.g. 3840 for 4K
    fps_above: float | None = None  # match when source fps > this value


@dataclass
class ConvertResult:
    source: Path
    output: Path
    status: str  # ok | skip | error
    orig_bytes: int = 0
    out_bytes: int = 0
    message: str = ""
    source_info: str = ""


def parse_size(value: str) -> int:
    """Parse human sizes like 100M, 1.5G, 50000000."""
    raw = value.strip()
    if raw.isdigit():
        return int(raw)
    match = _SIZE_RE.match(raw)
    if not match:
        raise argparse.ArgumentTypeError(
            f"Invalid size {value!r}; use e.g. 100M, 1G, or bytes"
        )
    number = float(match.group(1))
    unit = (match.group(2) or "").upper()
    if not unit:
        return int(number)
    return int(number * _SIZE_UNITS[unit])


def format_bytes(num: int) -> str:
    if num < 1024:
        return f"{num} B"
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        num_f = num / 1024
        if num_f < 1024:
            return f"{num_f:.1f} {unit}"
        num = int(num_f)
    return f"{num / 1024:.1f} PiB"


def pct_smaller(orig: int, new: int) -> str:
    if orig <= 0:
        return "n/a"
    saved = savings_pct(orig, new)
    if saved >= 0:
        return f"{saved:.1f}% smaller"
    return f"{-saved:.1f}% larger"


def savings_pct(orig: int, new: int) -> float:
    if orig <= 0:
        return 0.0
    return (1 - new / orig) * 100


def format_bitrate(bps: int | None) -> str:
    if not bps:
        return "?"
    mbps = bps / 1_000_000
    if mbps >= 10:
        return f"{mbps:.0f}Mbps"
    return f"{mbps:.1f}Mbps"


def parse_frame_rate(raw: str | None) -> float | None:
    if not raw:
        return None
    if "/" in raw:
        num, den = raw.split("/", 1)
        try:
            den_f = float(den)
            if den_f == 0:
                return None
            return float(num) / den_f
        except ValueError:
            return None
    try:
        return float(raw)
    except ValueError:
        return None


def format_fps(fps: float | None) -> str:
    if fps is None:
        return "?"
    if abs(fps - round(fps)) < 0.01:
        return f"{round(fps):.0f}fps"
    return f"{fps:.2f}fps"


def long_edge(probe: VideoProbe) -> int:
    return max(probe.width, probe.height)


def scan_needs_probe(criteria: ScanCriteria) -> bool:
    return criteria.min_long_edge is not None or criteria.fps_above is not None


def matches_criteria(
    path: Path,
    probe: VideoProbe | None,
    criteria: ScanCriteria,
) -> bool:
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if criteria.min_bytes and size <= criteria.min_bytes:
        return False
    if criteria.min_long_edge is not None:
        if probe is None:
            return False
        if long_edge(probe) < criteria.min_long_edge:
            return False
    if criteria.fps_above is not None:
        if probe is None or probe.fps is None:
            return False
        if probe.fps <= criteria.fps_above:
            return False
    return True


def probe_video(path: Path) -> VideoProbe | None:
    if not shutil.which("ffprobe"):
        return None
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height,bit_rate,duration,avg_frame_rate,r_frame_rate",
                "-show_entries",
                "format=bit_rate,duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(proc.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
        return None

    streams = data.get("streams") or []
    if not streams:
        return None
    stream = streams[0]
    fmt = data.get("format") or {}

    bitrate_raw = stream.get("bit_rate") or fmt.get("bit_rate")
    bitrate = int(bitrate_raw) if bitrate_raw else None
    if not bitrate:
        duration_raw = stream.get("duration") or fmt.get("duration")
        try:
            duration = float(duration_raw) if duration_raw else None
        except ValueError:
            duration = None
        if duration and duration > 0:
            bitrate = int(path.stat().st_size * 8 / duration)
    else:
        duration_raw = stream.get("duration") or fmt.get("duration")
        try:
            duration = float(duration_raw) if duration_raw else None
        except ValueError:
            duration = None

    fps = parse_frame_rate(stream.get("avg_frame_rate"))
    if fps is None:
        fps = parse_frame_rate(stream.get("r_frame_rate"))

    return VideoProbe(
        codec=str(stream.get("codec_name") or "?"),
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        bitrate=bitrate,
        duration=duration,
        fps=fps,
    )


def scaled_dimensions(width: int, height: int, max_dimension: int) -> tuple[int, int]:
    """Target WxH after capping the longer edge (never upscale)."""
    if width <= 0 or height <= 0:
        return width, height
    long_edge = max(width, height)
    if long_edge <= max_dimension:
        return width, height
    scale = max_dimension / long_edge
    out_w = int(round(width * scale))
    out_h = int(round(height * scale))
    # H.264/x265 need even dimensions
    return out_w - (out_w % 2), out_h - (out_h % 2)


def scale_filter(max_dimension: int) -> str:
    """ffmpeg scale expression: cap longer edge, preserve aspect, Lanczos."""
    m = max_dimension
    return (
        f"scale=w='if(gt(iw\\,ih)\\,min(iw\\,{m})\\,-2)'"
        f":h='if(gt(ih\\,iw)\\,min(ih\\,{m})\\,-2)'"
        f":flags=lanczos"
    )


def video_filter_chain(
    max_dimension: int,
    max_fps: float | None,
    probe: VideoProbe | None,
) -> str:
    """Scale (long-edge cap) and optionally drop fps when source exceeds max_fps."""
    parts = [scale_filter(max_dimension)]
    if max_fps is not None and probe and probe.fps and probe.fps > max_fps:
        parts.append(f"fps={max_fps}")
    return ",".join(parts)


def probe_summary(
    probe: VideoProbe | None,
    max_dimension: int | None = None,
    *,
    max_fps: float | None = None,
) -> str:
    if probe is None:
        return ""
    res = f"{probe.width}x{probe.height}" if probe.width and probe.height else "?"
    if max_dimension and probe.width and probe.height:
        out_w, out_h = scaled_dimensions(probe.width, probe.height, max_dimension)
        if out_w != probe.width or out_h != probe.height:
            res = f"{res} -> {out_w}x{out_h}"
    if max_fps is not None and probe.fps and probe.fps > max_fps:
        res = f"{res} @{format_fps(probe.fps)} -> {format_fps(max_fps)}"
    elif probe.fps:
        res = f"{res} @{format_fps(probe.fps)}"
    return f"[{probe.codec} {res} ~{format_bitrate(probe.bitrate)}]"


def is_already_efficient(
    probe: VideoProbe,
    max_dimension: int,
    *,
    max_bitrate_bps: int = 12_000_000,
) -> bool:
    """Skip re-encode when source is already HEVC at/below target with moderate bitrate."""
    if probe.codec not in ("hevc", "h265"):
        return False
    long_edge = max(probe.width, probe.height)
    if long_edge > max_dimension:
        return False
    if probe.bitrate and probe.bitrate > max_bitrate_bps:
        return False
    return True


def next_archive_dir(cwd: Path, base_name: str = "archive") -> Path:
    candidate = cwd / base_name
    if not candidate.exists():
        return candidate
    n = 1
    while (cwd / f"{base_name}_{n}").exists():
        n += 1
    return cwd / f"{base_name}_{n}"


def is_video_file(path: Path) -> bool:
    return path.suffix.casefold() in VIDEO_EXTENSIONS


def is_convert_output_artifact(path: Path) -> bool:
    """Skip files that look like prior encode outputs beside sources."""
    if path.suffix.casefold() != ".mp4":
        return False
    stem = path.stem
    return stem.endswith("_reencode") or stem.endswith("_convert")


def log_skip_convert_artifact(path: Path) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"{ts} SKIP {path} (prior encode artifact)"


def iter_matching_videos(root: Path, criteria: ScanCriteria) -> tuple[list[Path], list[Path]]:
    files: list[Path] = []
    skipped_convert: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or not is_video_file(path):
            continue
        if is_convert_output_artifact(path):
            skipped_convert.append(path)
            continue
        probe: VideoProbe | None = None
        if scan_needs_probe(criteria):
            probe = probe_video(path)
        if not matches_criteria(path, probe, criteria):
            continue
        files.append(path)
    files.sort(key=lambda p: p.stat().st_size, reverse=True)
    skipped_convert.sort(key=lambda p: p.name.casefold())
    return files, skipped_convert


def criteria_summary(criteria: ScanCriteria) -> str:
    parts: list[str] = []
    if criteria.min_bytes:
        parts.append(f"size>{format_bytes(criteria.min_bytes)}")
    if criteria.min_long_edge is not None:
        if criteria.min_long_edge >= UHD_4K_LONG_EDGE:
            parts.append("4K+")
        elif criteria.min_long_edge >= ABOVE_1080P_LONG_EDGE:
            parts.append(">1080p")
        elif criteria.min_long_edge >= ABOVE_720P_LONG_EDGE:
            parts.append(">720p")
        else:
            parts.append(f"long>={criteria.min_long_edge}px")
    if criteria.fps_above is not None:
        parts.append(f"fps>{criteria.fps_above:g}")
    return ", ".join(parts) if parts else "all videos"


def output_path_for(
    source: Path,
    input_root: Path,
    output_root: Path,
) -> Path:
    try:
        rel = source.resolve().relative_to(input_root.resolve())
    except ValueError:
        rel = Path(source.name)
    return output_root / rel.with_suffix(CANONICAL_VIDEO_EXT)


def in_place_output_path(source: Path) -> Path:
    return source.with_suffix(CANONICAL_VIDEO_EXT)




def reencode_output_path(source: Path, suffix: str) -> Path:
    """Write re-encode output beside the source (same directory as B)."""
    return source.parent / f"{source.stem}{suffix}"


def resolve_output_path(
    source: Path,
    input_root: Path,
    output_root: Path | None,
    *,
    reencode: bool,
    output_suffix: str,
    in_place: bool,
) -> Path:
    if reencode:
        return reencode_output_path(source, output_suffix)
    if in_place or output_root is None:
        return in_place_output_path(source)
    return output_path_for(source, input_root, output_root)

def resolve_thread_budget(
    jobs: int,
    *,
    ffmpeg_threads: int | None,
    x265_frame_threads: int,
) -> tuple[int, int]:
    cpu = os.cpu_count() or 4
    jobs = max(1, jobs)
    if ffmpeg_threads is None:
        ff = 0 if jobs == 1 else max(1, cpu // jobs)
    else:
        ff = ffmpeg_threads
    if jobs == 1:
        frame = x265_frame_threads
    else:
        cap = max(1, ff or cpu // jobs)
        frame = min(x265_frame_threads, cap)
    return ff, frame


def print_thread_budget(
    jobs: int,
    ffmpeg_threads: int,
    x265_frame_threads: int,
) -> None:
    cpu = os.cpu_count() or 4
    per_job = ffmpeg_threads if ffmpeg_threads else cpu
    total = jobs * per_job
    ff_label = str(ffmpeg_threads) if ffmpeg_threads else f"0 (all {cpu})"
    print(
        f"CPU budget: cores={cpu} jobs={jobs} ffmpeg_threads={ff_label} "
        f"x265_frame_threads={x265_frame_threads} (~{total} encode threads total)",
        file=sys.stderr,
    )
    if jobs > 1 and total > cpu:
        print(
            "WARNING: parallel jobs may oversubscribe CPU and run slower; "
            "try --jobs 1 for best throughput with x265",
            file=sys.stderr,
        )


def ffmpeg_cmd(
    source: Path,
    dest: Path,
    *,
    max_dimension: int,
    max_fps: float | None,
    probe: VideoProbe | None,
    crf: int,
    preset: str,
    audio_bitrate: str,
    ffmpeg_threads: int,
    x265_frame_threads: int,
) -> list[str]:
    # Lanczos downscale; yuv420p + hvc1 tag for broad player support.
    # Cap the longer edge (default 1920) so portrait 1080x1920 stays full width.
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-threads",
        str(ffmpeg_threads),
        "-map_metadata",
        "0",
        "-vf",
        video_filter_chain(max_dimension, max_fps, probe),
        "-c:v",
        "libx265",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-pix_fmt",
        "yuv420p",
        "-tag:v",
        "hvc1",
        "-x265-params",
        f"pools=+:frame-threads={x265_frame_threads}:aq-mode=3:psy-rd=2.0:psy-rdoq=1.0",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-movflags",
        "+use_metadata_tags",
        str(dest),
    ]


def ffmpeg_remux_cmd(source: Path, dest: Path, *, probe: VideoProbe | None) -> list[str]:
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
        "-map",
        "0",
        "-c",
        "copy",
        "-movflags",
        "+use_metadata_tags",
    ]
    if probe and probe.codec in ("hevc", "h265"):
        cmd.extend(["-tag:v", "hvc1"])
    cmd.append(str(dest))
    return cmd


def remux_to_mp4(
    source: Path,
    dest: Path,
    *,
    probe: VideoProbe | None,
    orig_bytes: int,
    dry_run: bool,
    info: str,
    reason: str,
) -> ConvertResult:
    if dry_run:
        return ConvertResult(
            source,
            dest,
            "ok",
            orig_bytes=orig_bytes,
            message=f"dry-run remux ({reason})",
            source_info=info,
        )

    if not shutil.which("ffmpeg"):
        return ConvertResult(
            source,
            dest,
            "error",
            orig_bytes=orig_bytes,
            message="ffmpeg not found",
            source_info=info,
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.casefold() == ".mp4":
        try:
            shutil.copy2(source, dest)
        except OSError as exc:
            return ConvertResult(
                source, dest, "error", orig_bytes=orig_bytes, message=str(exc), source_info=info
            )
    else:
        try:
            subprocess.run(
                ffmpeg_remux_cmd(source, dest, probe=probe),
                check=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as exc:
            dest.unlink(missing_ok=True)
            err = (exc.stderr or b"").decode(errors="replace").strip()
            return ConvertResult(
                source,
                dest,
                "error",
                orig_bytes=orig_bytes,
                message=err or f"remux failed (exit {exc.returncode})",
                source_info=info,
            )
        except OSError as exc:
            dest.unlink(missing_ok=True)
            return ConvertResult(
                source, dest, "error", orig_bytes=orig_bytes, message=str(exc), source_info=info
            )

    try:
        out_bytes = dest.stat().st_size
    except OSError as exc:
        return ConvertResult(
            source,
            dest,
            "error",
            orig_bytes=orig_bytes,
            message=f"remuxed but unreadable: {exc}",
            source_info=info,
        )

    action = "copy" if source.suffix.casefold() == ".mp4" else "remux"
    return ConvertResult(
        source,
        dest,
        "ok",
        orig_bytes=orig_bytes,
        out_bytes=out_bytes,
        message=f"{action} ({reason})",
        source_info=info,
    )


def convert_one(
    source: Path,
    input_root: Path,
    output_root: Path | None,
    *,
    max_dimension: int,
    max_fps: float | None,
    crf: int,
    preset: str,
    audio_bitrate: str,
    ffmpeg_threads: int,
    x265_frame_threads: int,
    dry_run: bool,
    force: bool,
    skip_efficient: bool,
    min_savings_pct: float,
    reencode: bool = False,
    output_suffix: str = CANONICAL_VIDEO_EXT,
    remux_if_skip: bool = False,
    in_place: bool = False,
) -> ConvertResult:
    source = source.resolve()
    dest = resolve_output_path(
        source,
        input_root,
        output_root,
        reencode=reencode,
        output_suffix=output_suffix,
        in_place=in_place,
    )
    try:
        orig_bytes = source.stat().st_size
    except OSError as exc:
        return ConvertResult(source, dest, "error", message=str(exc))

    probe = probe_video(source)
    info = probe_summary(probe, max_dimension, max_fps=max_fps)

    if dest.is_file() and force and not dry_run:
        dest.unlink(missing_ok=True)

    if dest.is_file():
        try:
            out_bytes = dest.stat().st_size
        except OSError:
            out_bytes = 0
        return ConvertResult(
            source,
            dest,
            "skip",
            orig_bytes=orig_bytes,
            out_bytes=out_bytes,
            message="output already exists",
            source_info=info,
        )

    if not reencode and skip_efficient and probe and is_already_efficient(probe, max_dimension):
        if remux_if_skip:
            return remux_to_mp4(
                source,
                dest,
                probe=probe,
                orig_bytes=orig_bytes,
                dry_run=dry_run,
                info=info,
                reason="already efficient HEVC at target resolution",
            )
        return ConvertResult(
            source,
            dest,
            "skip",
            orig_bytes=orig_bytes,
            message="already efficient HEVC at target resolution",
            source_info=info,
        )

    if dry_run:
        return ConvertResult(
            source,
            dest,
            "ok",
            orig_bytes=orig_bytes,
            message="dry-run",
            source_info=info,
        )

    if not shutil.which("ffmpeg"):
        return ConvertResult(
            source, dest, "error", orig_bytes=orig_bytes, message="ffmpeg not found", source_info=info
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ffmpeg_cmd(
        source,
        dest,
        max_dimension=max_dimension,
        max_fps=max_fps,
        probe=probe,
        crf=crf,
        preset=preset,
        audio_bitrate=audio_bitrate,
        ffmpeg_threads=ffmpeg_threads,
        x265_frame_threads=x265_frame_threads,
    )
    try:
        subprocess.run(cmd, check=True, capture_output=True, stdin=subprocess.DEVNULL)
    except subprocess.CalledProcessError as exc:
        dest.unlink(missing_ok=True)
        err = (exc.stderr or b"").decode(errors="replace").strip()
        return ConvertResult(
            source,
            dest,
            "error",
            orig_bytes=orig_bytes,
            message=err or f"ffmpeg exit {exc.returncode}",
            source_info=info,
        )
    except OSError as exc:
        dest.unlink(missing_ok=True)
        return ConvertResult(
            source, dest, "error", orig_bytes=orig_bytes, message=str(exc), source_info=info
        )

    try:
        out_bytes = dest.stat().st_size
    except OSError as exc:
        return ConvertResult(
            source,
            dest,
            "error",
            orig_bytes=orig_bytes,
            message=f"converted but unreadable: {exc}",
            source_info=info,
        )

    saved = savings_pct(orig_bytes, out_bytes)
    should_remux = remux_if_skip and not reencode and (
        saved < 0
        or (min_savings_pct > 0 and saved < min_savings_pct)
    )
    if should_remux:
        dest.unlink(missing_ok=True)
        if saved < 0:
            reason = f"encode would be {abs(saved):.1f}% larger"
        else:
            reason = f"encode only {saved:.1f}% smaller (min {min_savings_pct:g}%)"
        return remux_to_mp4(
            source,
            dest,
            probe=probe,
            orig_bytes=orig_bytes,
            dry_run=False,
            info=info,
            reason=reason,
        )

    if not reencode and min_savings_pct > 0 and saved < min_savings_pct:
        dest.unlink(missing_ok=True)
        return ConvertResult(
            source,
            dest,
            "skip",
            orig_bytes=orig_bytes,
            out_bytes=out_bytes,
            message=(
                f"only {saved:.1f}% smaller (min {min_savings_pct:g}%), kept original"
            ),
            source_info=info,
        )

    return ConvertResult(
        source,
        dest,
        "ok",
        orig_bytes=orig_bytes,
        out_bytes=out_bytes,
        source_info=info,
    )


def log_line(result: ConvertResult) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    info = f" {result.source_info}" if result.source_info else ""
    if result.status == "skip":
        return (
            f"{ts} SKIP {result.source}{info} "
            f"({format_bytes(result.orig_bytes)}) -> {result.output} ({result.message})"
        )
    if result.status == "error":
        return (
            f"{ts} ERROR {result.source}{info} "
            f"({format_bytes(result.orig_bytes)}) -> {result.output}: {result.message}"
        )
    if result.message == "dry-run":
        return (
            f"{ts} DRY-RUN {result.source}{info} "
            f"({format_bytes(result.orig_bytes)}) -> {result.output}"
        )
    extra = f" [{result.message}]" if result.message else ""
    return (
        f"{ts} OK {result.source}{info} "
        f"{format_bytes(result.orig_bytes)} -> {format_bytes(result.out_bytes)} "
        f"({pct_smaller(result.orig_bytes, result.out_bytes)}){extra} -> {result.output}"
    )


def _worker(item: tuple) -> ConvertResult:
    path, in_root, out_root, kw = item
    return convert_one(path, in_root, out_root, **kw)


def build_scan_criteria(
    *,
    min_bytes: int = 0,
    min_long_edge: int | None = None,
    above_720p: bool = False,
    above_1080p: bool = False,
    four_k: bool = False,
    fps_above: float | None = None,
) -> ScanCriteria:
    edge_thresholds: list[int] = []
    if min_long_edge is not None:
        edge_thresholds.append(min_long_edge)
    if above_720p:
        edge_thresholds.append(ABOVE_720P_LONG_EDGE)
    if above_1080p:
        edge_thresholds.append(ABOVE_1080P_LONG_EDGE)
    if four_k:
        edge_thresholds.append(UHD_4K_LONG_EDGE)
    resolved_edge = max(edge_thresholds) if edge_thresholds else None
    return ScanCriteria(
        min_bytes=min_bytes,
        min_long_edge=resolved_edge,
        fps_above=fps_above,
    )


def build_scan_criteria_from_args(args: argparse.Namespace) -> ScanCriteria:
    return build_scan_criteria(
        min_bytes=args.min_size,
        min_long_edge=args.min_long_edge,
        above_720p=args.above_720p,
        above_1080p=args.above_1080p,
        four_k=args.four_k,
        fps_above=args.fps_above,
    )


def result_log_status(result: ConvertResult) -> str:
    if result.message in ("dry-run", "dry_run"):
        return "dry_run"
    return result.status


def result_action(result: ConvertResult) -> str:
    if result.message.startswith("remux") or "remux" in result.message:
        return "remux"
    if result.message.startswith("copy"):
        return "copy"
    return "convert"
