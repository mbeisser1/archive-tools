"""Copy embedded file metadata after format conversion or re-encoding."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_warned_missing = False


def exiftool_available() -> bool:
    return shutil.which("exiftool") is not None


def warn_if_missing() -> None:
    global _warned_missing
    if _warned_missing or exiftool_available():
        return
    _warned_missing = True
    print(
        "WARNING: exiftool not found; embedded metadata will not be preserved on convert/compress",
        file=sys.stderr,
    )


def _log_metadata_error(source: Path, dest: Path, message: str) -> None:
    print(
        f"WARNING: metadata copy failed ({source} -> {dest}): {message}",
        file=sys.stderr,
    )


def copy_metadata(source: Path, dest: Path) -> bool:
    """Copy EXIF/XMP/tags from source onto dest (in place). Returns True on success."""
    if not source.is_file():
        _log_metadata_error(source, dest, "source file missing")
        return False
    if not dest.is_file():
        _log_metadata_error(source, dest, "destination file missing")
        return False
    if not exiftool_available():
        return False

    try:
        subprocess.run(
            [
                "exiftool",
                "-TagsFromFile",
                str(source),
                "-all:all",
                "-overwrite_original",
                str(dest),
            ],
            check=True,
            capture_output=True,
        )
        backup = dest.with_name(f"{dest.name}_original")
        backup.unlink(missing_ok=True)
        return True
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode(errors="replace").strip()
        if detail:
            _log_metadata_error(source, dest, detail)
        else:
            _log_metadata_error(source, dest, f"exiftool exited {exc.returncode}")
        return False
