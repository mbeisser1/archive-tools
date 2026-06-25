#!/usr/bin/env python3
"""Remove VCF entries whose phone numbers appear in another VCF file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.ensure_vcf_venv import bootstrap_vcf_venv  # noqa: E402

bootstrap_vcf_venv()

from lib.vcf import load_vcards, print_subtract_report, subtract_vcards, write_vcards  # noqa: E402


def default_output_path(base_path: Path) -> Path:
    return base_path.with_name(f"{base_path.stem}.subtracted.vcf")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Remove contacts from a VCF when any of their phone numbers "
            "appear in an exclude VCF."
        )
    )
    parser.add_argument("base_vcf", type=Path, help="VCF to filter (e.g. staging/combined.vcf)")
    parser.add_argument(
        "exclude_vcf",
        type=Path,
        help="VCF whose phones are removed from base (e.g. staging/contacts_gosms.vcf)",
    )
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
        help="Write filtered VCF here (default: <base>.subtracted.vcf beside the base file)",
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

    base_path = args.base_vcf.resolve()
    exclude_path = args.exclude_vcf.resolve()
    output_path = args.output.resolve() if args.output else default_output_path(base_path)

    if not base_path.is_file():
        print(f"ERROR: Base VCF not found: {base_path}", file=sys.stderr)
        return 1
    if not exclude_path.is_file():
        print(f"ERROR: Exclude VCF not found: {exclude_path}", file=sys.stderr)
        return 1

    base_vcards = load_vcards(base_path)
    exclude_vcards = load_vcards(exclude_path)
    kept, report = subtract_vcards(
        base_vcards,
        exclude_vcards,
        args.country,
        sms_tag=not args.no_sms_tag,
        one_name_one_phone=not args.allow_duplicate_names,
    )
    print_subtract_report(report, base_path, exclude_path)

    if args.dry_run:
        print(f"\nDry run — would write {len(kept)} vCard(s) to {output_path}")
        return 0

    write_vcards(output_path, kept)
    print(f"\nWrote {len(kept)} vCard(s) to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
