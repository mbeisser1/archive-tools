"""TSV operation log with human-readable stdout lines."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

TSV_COLUMNS = (
    "timestamp_utc",
    "operation",
    "status",
    "source_path",
    "dest_path",
    "action",
    "message",
    "bytes_in",
    "bytes_out",
)

STATUS_OK = "ok"
STATUS_SKIP = "skip"
STATUS_ERROR = "error"
STATUS_DRY_RUN = "dry_run"


@dataclass
class LogEntry:
    operation: str
    status: str
    source: Path
    dest: Path | None = None
    action: str = ""
    message: str = ""
    bytes_in: int | None = None
    bytes_out: int | None = None

    def human_line(self) -> str:
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        dest = self.dest or ""
        if self.status == STATUS_SKIP:
            return f"{ts} SKIP {self.source} -> {dest} ({self.message})"
        if self.status == STATUS_ERROR:
            return f"{ts} ERROR {self.source} -> {dest}: {self.message}"
        if self.status == STATUS_DRY_RUN:
            return f"{ts} DRY-RUN {self.source} -> {dest}"
        extra = f" ({self.message})" if self.message else ""
        size = ""
        if self.bytes_in is not None and self.bytes_out is not None:
            size = f" {self.bytes_in} -> {self.bytes_out} bytes"
        return f"{ts} OK {self.source} -> {dest}{size}{extra}"

    @property
    def timestamp(self) -> datetime:
        return datetime.now(timezone.utc)

    def tsv_row(self) -> list[str]:
        return [
            self.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            self.operation,
            self.status,
            str(self.source),
            str(self.dest) if self.dest else "",
            self.action,
            self.message,
            str(self.bytes_in) if self.bytes_in is not None else "",
            str(self.bytes_out) if self.bytes_out is not None else "",
        ]


class TsvLog:
    def __init__(
        self,
        *,
        tool: str,
        input_path: Path,
        output_path: Path | None,
        dry_run: bool,
        log_path: Path,
    ) -> None:
        self.tool = tool
        self.input_path = input_path
        self.output_path = output_path
        self.dry_run = dry_run
        self.log_path = log_path
        self._started = datetime.now(timezone.utc)
        self._handle = None
        self._counts = {"ok": 0, "skip": 0, "error": 0, "dry_run": 0}

    def open(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.log_path.open("w", encoding="utf-8")
        self._handle.write("# archive-tools log\n")
        self._handle.write(f"# tool: {self.tool}\n")
        self._handle.write(f"# input: {self.input_path}\n")
        out = self.output_path if self.output_path else "(in-place)"
        self._handle.write(f"# output: {out}\n")
        self._handle.write(f"# dry_run: {str(self.dry_run).lower()}\n")
        self._handle.write(f"# started: {self._started.strftime('%Y-%m-%dT%H:%M:%SZ')}\n")
        self._handle.write("\t".join(TSV_COLUMNS) + "\n")

    def write(self, entry: LogEntry) -> None:
        if self._handle is None:
            self.open()
        print(entry.human_line())
        self._handle.write("\t".join(entry.tsv_row()) + "\n")
        self._handle.flush()
        if entry.status in self._counts:
            self._counts[entry.status] += 1

    def close(self) -> int:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        c = self._counts
        print(
            f"\nDone: {c['ok']} ok, {c['skip']} skipped, "
            f"{c['error']} error(s), {c['dry_run']} dry-run",
            file=sys.stderr,
        )
        print(f"Log: {self.log_path}", file=sys.stderr)
        return 1 if c["error"] else 0
