"""EXIF-based media renaming."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

DATE_TAGS = ("DateTimeOriginal", "CreateDate", "ModifyDate")

EXIF_FORMATS = (
    "%Y:%m:%d %H:%M:%S",
    "%Y:%m:%d %H:%M",
    "%Y:%m:%d",
)

MEDIA_EXTENSIONS = frozenset({
    "jpg", "jpeg", "png", "tif", "tiff", "heic", "heif", "webp", "gif",
    "mp4", "mov", "avi", "mkv", "m4v", "mpg", "mpeg", "3gp",
})

EXIF_BATCH_SIZE = 500
_READY_LINE = "{ready}"


def require_exiftool() -> str:
    exiftool = shutil.which("exiftool")
    if not exiftool:
        raise RuntimeError("exiftool not found on PATH")
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


def capture_datetime_from_record(record: dict) -> datetime | None:
    for tag in DATE_TAGS:
        raw = record.get(tag)
        if raw is None:
            continue
        dt = parse_exif_datetime(str(raw))
        if dt is not None:
            return dt
    return None


def read_capture_datetime(exiftool: str, path: Path) -> datetime | None:
    """Read capture time for one file (slow — prefer ExifToolSession batch reads)."""
    for tag in DATE_TAGS:
        raw = read_exif_raw(exiftool, path, tag)
        if raw is None:
            continue
        return parse_exif_datetime(raw)
    return None


class ExifToolSession:
    """Long-lived exiftool process for batch metadata reads (-stay_open True)."""

    def __init__(self, exiftool: str | None = None) -> None:
        self._exiftool = exiftool or require_exiftool()
        self._proc = subprocess.Popen(
            [self._exiftool, "-stay_open", "True", "-@", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def __enter__(self) -> ExifToolSession:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        proc = self._proc
        self._proc = None  # type: ignore[assignment]
        if proc is None or proc.stdin is None:
            return
        try:
            proc.stdin.write("-stay_open\nFalse\n")
            proc.stdin.flush()
            proc.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()

    def read_capture_datetimes(self, paths: list[Path]) -> dict[Path, datetime | None]:
        """Batch-read capture datetimes; paths are chunked internally."""
        if not paths:
            return {}

        result: dict[Path, datetime | None] = {}
        for start in range(0, len(paths), EXIF_BATCH_SIZE):
            chunk = paths[start : start + EXIF_BATCH_SIZE]
            result.update(self._read_capture_datetimes_batch(chunk))
        return result

    def _read_capture_datetimes_batch(
        self, paths: list[Path]
    ) -> dict[Path, datetime | None]:
        resolved = [path.resolve() for path in paths]
        command = [*DATE_TAGS, "-json", *(str(path) for path in resolved), "-execute"]
        self._send_command(command)
        payload = self._read_response()
        return self._parse_json_dates(payload, resolved)

    def _send_command(self, command: list[str]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("exiftool session is closed")
        self._proc.stdin.write("\n".join(command) + "\n")
        self._proc.stdin.flush()

    def _read_response(self) -> str:
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("exiftool session is closed")
        lines: list[str] = []
        while True:
            line = self._proc.stdout.readline()
            if line == "":
                raise RuntimeError("exiftool closed stdout unexpectedly")
            if line.rstrip() == _READY_LINE:
                break
            lines.append(line)
        return "".join(lines)

    def _parse_json_dates(
        self, payload: str, paths: list[Path]
    ) -> dict[Path, datetime | None]:
        by_path: dict[Path, datetime | None] = {path: None for path in paths}
        payload = payload.strip()
        if not payload:
            return by_path

        try:
            records = json.loads(payload)
        except json.JSONDecodeError:
            return by_path

        if isinstance(records, dict):
            records = [records]

        for record in records:
            source_raw = record.get("SourceFile")
            if not source_raw:
                continue
            source = Path(str(source_raw)).resolve()
            by_path[source] = capture_datetime_from_record(record)

        return by_path


def format_stem(dt: datetime) -> str:
    return f"{dt:%Y-%m-%d}__{dt:%H-%M-%S}"


def build_name_suffix_style(suffix: str, dt: datetime, ext: str) -> str:
    return f"{format_stem(dt)}-{suffix}.{ext.lower()}"


def build_name_prefix_style(prefix: str, dt: datetime, ext: str) -> str:
    return f"{prefix}-{format_stem(dt)}.{ext.lower()}"


def already_renamed_pattern(label: str, *, use_prefix: bool) -> re.Pattern[str]:
    if use_prefix:
        return re.compile(
            rf"^{re.escape(label)}-\d{{4}}-\d{{2}}-\d{{2}}__\d{{2}}-\d{{2}}-\d{{2}}\.",
            re.IGNORECASE,
        )
    return re.compile(
        rf"^\d{{4}}-\d{{2}}-\d{{2}}__\d{{2}}-\d{{2}}-\d{{2}}-{re.escape(label)}\.",
        re.IGNORECASE,
    )


def slot_taken(slot: str, directory: Path, claimed_slots: set[str]) -> bool:
    if slot in claimed_slots:
        return True
    prefix = slot + "."
    return any(
        path.is_file() and path.name.startswith(prefix)
        for path in directory.iterdir()
    )


def next_available_name(
    label: str,
    dt: datetime,
    ext: str,
    dest_dir: Path,
    *,
    use_prefix: bool,
    claimed: set[str],
    claimed_slots: set[str],
) -> str:
    for bump in range(60):
        new_second = dt.second + bump
        if new_second > 59:
            break
        candidate_dt = dt.replace(second=new_second)
        if use_prefix:
            slot = format_stem(candidate_dt)
            name = build_name_prefix_style(label, candidate_dt, ext)
        else:
            slot = f"{format_stem(candidate_dt)}-{label}"
            name = build_name_suffix_style(label, candidate_dt, ext)
        if slot_taken(slot, dest_dir, claimed_slots):
            continue
        if name in claimed or (dest_dir / name).exists():
            continue
        claimed.add(name)
        claimed_slots.add(slot)
        return name
    raise RuntimeError(f"Too many collisions for {format_stem(dt)} in {dest_dir}")


def iter_media_files(root: Path) -> list[Path]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lstrip(".").lower() in MEDIA_EXTENSIONS
    ]
    files.sort(key=lambda p: p.as_posix().casefold())
    return files
