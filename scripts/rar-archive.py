#!/usr/bin/env python3
"""Create RAR5 archives — thin wrapper around rar with fixed archival defaults.

Defaults: -ma5 -htb -m4 -rr2% -v2g (2 GiB) -r
Optional: -m N, --rr PCT, --md SIZE (e.g. 128m), --prefix, -r false
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_VOLUME = "2g"  # lowercase g = GiB (× 1024³), not decimal GB


def parse_bool(value: str | bool) -> bool:
    if value is True:
        return True
    if value is False:
        return False
    text = str(value).strip().lower()
    if text in ("false", "0", "no", "n"):
        return False
    if text in ("true", "1", "yes", "y"):
        return True
    raise argparse.ArgumentTypeError(f"expected true or false, got {value!r}")


def archive_name(input_dir: Path, prefix: str) -> str:
    base = input_dir.name or "archive"
    if prefix:
        return f"{prefix}-{base}.rar"
    return f"{base}.rar"


def build_rar_command(
    archive: str,
    input_dir: Path,
    *,
    method: str,
    recurse: bool,
    recovery: str,
    dictionary: str | None,
    volume: str = DEFAULT_VOLUME,
) -> list[str]:
    cmd = [
        "rar",
        "a",
        "-ma5",
        "-htb",
        f"-m{method}",
        f"-rr{recovery}",
        f"-v{volume}",
    ]
    if dictionary:
        cmd.append(f"-md{dictionary}")
    if recurse:
        cmd.append("-r")
    cmd.extend([archive, str(input_dir)])
    return cmd


def print_help(*, stream: object = None) -> None:
    out = stream if stream is not None else sys.stdout
    print(
        f"""\
rar-archive.py — create RAR5 archives

defaults: -ma5 -htb -m4 -rr2% -v2g -r
          volume size = 2 GiB (lowercase g), not decimal 2 GB (-v2G)

RAR size suffixes (-v volume, --md dictionary):
  exact   b     bytes
  binary  k     KiB  (× 1,024)
          m     MiB  (× 1,024²)
          g     GiB  (× 1,024³)
  decimal K     × 1,000
          M     MB   (× 1,000²)
          G     GB   (× 1,000³)

  Lowercase = powers of 1024 (IEC: KiB, MiB, GiB).
  Uppercase = powers of 1000 (SI: KB, MB, GB).
  Example: -v2g → 2 GiB; -v2G → 2,000,000,000 bytes.

examples:
  rar-archive.py ./photos
      → photos.rar (2 GiB volumes by default)

  rar-archive.py --prefix backup ./photos
      → backup-photos.rar

  rar-archive.py -m 2 ./photos
      → use -m2 instead of default -m4

  rar-archive.py --rr 10% ./photos
      → 10% recovery record instead of default 2%

  rar-archive.py --md 128m ./photos
      → optional 128 MiB dictionary (omit for smaller RAM use)

  rar-archive.py -r false ./photos
      → do not recurse into subdirectories
""",
        file=out,  # type: ignore[arg-type]
    )


def print_examples(*, stream: object = None) -> None:
    print_help(stream=stream)


def main() -> int:
    if "-h" in sys.argv or "--help" in sys.argv:
        print_help()
        return 0

    parser = argparse.ArgumentParser(add_help=False, usage=argparse.SUPPRESS)
    parser.add_argument("input", type=Path)
    parser.add_argument("-m", default="4", metavar="N")
    parser.add_argument(
        "-r",
        "--recurse",
        nargs="?",
        const=True,
        default=True,
        type=parse_bool,
        metavar="BOOL",
    )
    parser.add_argument("--prefix", default="")
    parser.add_argument("--rr", default="2%", metavar="PCT")
    parser.add_argument(
        "--md",
        default=None,
        metavar="SIZE",
        help=argparse.SUPPRESS,
    )
    try:
        args = parser.parse_args()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print_examples(stream=sys.stderr)
            return 2
        return 0

    input_dir = args.input.expanduser().resolve()
    if not input_dir.is_dir():
        print(f"error: not a directory: {input_dir}", file=sys.stderr)
        return 1

    if not shutil.which("rar"):
        print("error: rar not found on PATH", file=sys.stderr)
        return 1

    out_name = archive_name(input_dir, args.prefix.strip())
    cmd = build_rar_command(
        out_name,
        input_dir,
        method=args.m,
        recurse=args.recurse,
        recovery=args.rr,
        dictionary=args.md,
    )

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"error: rar failed (exit {exc.returncode})", file=sys.stderr)
        return exc.returncode or 1

    print("Testing archive integrity...")
    try:
        subprocess.run(["rar", "t", out_name], check=True)
    except subprocess.CalledProcessError as exc:
        print(f"error: archive test failed (exit {exc.returncode})", file=sys.stderr)
        return exc.returncode or 1

    print(f"Archive created and tested: {out_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
