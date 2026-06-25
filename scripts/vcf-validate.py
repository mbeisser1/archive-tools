#!/usr/bin/env python3
"""Validate and standardize phone numbers in a VCF file to E.164."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.ensure_vcf_venv import bootstrap_vcf_venv  # noqa: E402

bootstrap_vcf_venv()

from lib.vcf import load_vcards, print_report, validate_vcards, write_vcards  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and standardize phone numbers in a VCF file to E.164."
    )
    parser.add_argument("vcf", type=Path, help="Path to VCF file")
    parser.add_argument(
        "-c",
        "--country",
        default="US",
        help="Default country for local numbers (default: US)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Update the input VCF in place (creates .vcf.bak backup)",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Report only; do not write changes (default without --fix or -o)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write standardized VCF to this path (default: update input in place)",
    )
    args = parser.parse_args()

    if not args.vcf.is_file():
        print(f"ERROR: VCF not found: {args.vcf}", file=sys.stderr)
        return 1

    vcards = load_vcards(args.vcf)
    write_changes = (args.fix or args.output) and not args.dry_run
    report = validate_vcards(vcards, args.country, apply=write_changes)
    exit_code = print_report(report, args.vcf)

    if not write_changes:
        return exit_code

    if args.output:
        write_vcards(args.output, vcards)
        print(f"\nWrote standardized VCF to {args.output}")
        return exit_code

    if report.normalized > 0:
        backup = args.vcf.with_suffix(args.vcf.suffix + ".bak")
        shutil.copy2(args.vcf, backup)
        write_vcards(args.vcf, vcards)
        print(f"\nUpdated {args.vcf} ({report.normalized} numbers normalized)")
        print(f"Backup: {backup}")
    else:
        print("\nNo changes needed.")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
