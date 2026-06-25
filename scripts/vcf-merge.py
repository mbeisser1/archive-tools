#!/usr/bin/env python3
"""Compare and merge VCF files by E.164 phone number (no duplicate phones)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.ensure_vcf_venv import bootstrap_vcf_venv  # noqa: E402

bootstrap_vcf_venv()

from lib.vcf import load_vcards, merge_vcards, print_merge_report, write_vcards  # noqa: E402


def default_output_path(base_path: Path) -> Path:
    return base_path.with_name(f"{base_path.stem}.merged.vcf")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare or merge VCF files; dedupe by E.164 phone number."
    )
    parser.add_argument("base_vcf", type=Path, help="Primary VCF (e.g. config/contacts.vcf)")
    parser.add_argument(
        "secondary_vcfs",
        type=Path,
        nargs="+",
        metavar="secondary_vcf",
        help="One or more VCFs to merge in (e.g. staging/contacts_gosms.vcf)",
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
        help="Write merged VCF here (default: <base>.merged.vcf beside the base file)",
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
    secondary_paths = [path.resolve() for path in args.secondary_vcfs]
    output_path = args.output.resolve() if args.output else default_output_path(base_path)

    if not base_path.is_file():
        print(f"ERROR: Base VCF not found: {base_path}", file=sys.stderr)
        return 1
    for secondary_path in secondary_paths:
        if not secondary_path.is_file():
            print(f"ERROR: Secondary VCF not found: {secondary_path}", file=sys.stderr)
            return 1

    merged = load_vcards(base_path)
    reports = []
    for index, secondary_path in enumerate(secondary_paths):
        secondary_vcards = load_vcards(secondary_path)
        merged, report = merge_vcards(
            merged,
            secondary_vcards,
            args.country,
            sms_tag=not args.no_sms_tag,
            one_name_one_phone=not args.allow_duplicate_names,
        )
        reports.append((secondary_path, report))
        if len(secondary_paths) > 1:
            print(f"\n--- {secondary_path.name} ---")
        base_label = None
        if len(secondary_paths) > 1 and index > 0:
            base_label = f"{base_path} + {index} prior secondary file(s)"
        print_merge_report(
            report,
            base_path,
            secondary_path,
            base_label=base_label,
        )

    total_to_add = sum(len(report.to_add) for _, report in reports)
    if args.dry_run:
        if total_to_add:
            print(f"\nDry run — would write {len(merged)} vCard(s) to {output_path}")
            print(f"  Added {total_to_add} phone(s) from secondary file(s)")
        return 0

    write_vcards(output_path, merged)
    print(f"\nWrote {len(merged)} vCard(s) to {output_path}")
    print(f"  Added {total_to_add} phone(s) from secondary file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
