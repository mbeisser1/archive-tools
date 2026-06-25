"""Shared CLI flags for archive-tools scripts."""

from __future__ import annotations

import argparse
from pathlib import Path


def add_io_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        required=True,
        help="Input file or directory",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output file or directory (optional; default is in-place / beside source)",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Plan only; no writes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing outputs",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        metavar="FILE",
        help="TSV log path (default: archive-tools.log beside output or input)",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="List matching files and exit",
    )
