#!/usr/bin/env python3
"""Clean a VCF: one named contact per phone, drop unknown and group labels."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.ensure_vcf_venv import bootstrap_vcf_venv  # noqa: E402

bootstrap_vcf_venv()

from lib.vcf import dedupe_vcards, load_vcards, print_dedupe_report, write_vcards  # noqa: E402


def default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}.deduped.vcf")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deduplicate a VCF to one named contact per E.164 phone. "
            "Drops (Unknown), bare numbers, and group MMS titles."
        )
    )
    parser.add_argument("input_vcf", type=Path, help="VCF to clean")
    parser.add_argument(
        "-c",
        "--country",
        default="US",
        help="Default country for phone normalization (default: US)",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Report only; do not write output",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write cleaned VCF here (default: <input>.deduped.vcf)",
    )
    parser.add_argument(
        "--no-sms-tag",
        action="store_true",
        help="Do not append __SMS__ to contact names in output",
    )
    parser.add_argument(
        "--allow-duplicate-names",
        action="store_true",
        help="Allow the same display name on multiple phone numbers",
    )
    args = parser.parse_args()

    input_path = args.input_vcf.resolve()
    output_path = args.output.resolve() if args.output else default_output_path(input_path)

    if not input_path.is_file():
        print(f"ERROR: VCF not found: {input_path}", file=sys.stderr)
        return 1

    vcards = load_vcards(input_path)
    cleaned, report = dedupe_vcards(
        vcards,
        args.country,
        sms_tag=not args.no_sms_tag,
        one_name_one_phone=not args.allow_duplicate_names,
    )
    print_dedupe_report(report, input_path)

    if args.dry_run:
        print(f"\nDry run — would write {len(cleaned)} vCard(s) to {output_path}")
        return 0

    write_vcards(output_path, cleaned)
    print(f"\nWrote {len(cleaned)} vCard(s) to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
