"""Validate, merge, dedupe, and subtract vCard contacts by E.164 phone."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import vobject

from lib.phone import is_named_contact, normalize_phone_number

SMS_VCF_NAME_SUFFIX = "__SMS__"


def contact_name(vcard) -> str:
    if "fn" in vcard.contents:
        return vcard.contents["fn"][0].value.strip()
    if "n" in vcard.contents:
        n = vcard.contents["n"][0].value
        parts = [n.given or "", n.family or ""]
        return " ".join(p for p in parts if p).strip()
    return "(unnamed)"


def vcard_phones(vcard, default_region: str) -> list[str]:
    """Return normalized E.164 numbers for a vCard (deduped, order preserved)."""
    phones: list[str] = []
    seen: set[str] = set()
    for tel in vcard.contents.get("tel", []):
        normalized = normalize_phone_number(tel.value, default_region)
        if normalized and normalized not in seen:
            seen.add(normalized)
            phones.append(normalized)
    return phones


def phone_name_index(vcards: list, default_region: str) -> dict[str, str]:
    """Map E.164 phone -> first contact name seen in vCard list."""
    index: dict[str, str] = {}
    for vcard in vcards:
        name = contact_name(vcard)
        for phone in vcard_phones(vcard, default_region):
            if phone not in index:
                index[phone] = name
    return index


def tagged_vcard_name(name: str, *, sms_tag: bool) -> str:
    if not sms_tag:
        return name
    if name.endswith(SMS_VCF_NAME_SUFFIX):
        return name
    return f"{name}{SMS_VCF_NAME_SUFFIX}"


def pick_better_name(existing: str, candidate: str) -> str:
    """Prefer fuller names (more words, then longer) over nicknames like Mom."""
    if existing.casefold() == candidate.casefold():
        return existing
    existing_words = len(existing.split())
    candidate_words = len(candidate.split())
    if candidate_words != existing_words:
        return candidate if candidate_words > existing_words else existing
    return candidate if len(candidate) > len(existing) else existing


@dataclass
class DedupeReport:
    input_vcards: int = 0
    skipped_no_phone: int = 0
    skipped_invalid_name: int = 0
    name_conflicts: list[tuple[str, str, str]] = field(default_factory=list)
    collapsed_name_dupes: list[tuple[str, str, str]] = field(default_factory=list)
    output_contacts: int = 0


def collapse_one_name_one_phone(
    registry: dict[str, str],
    report: DedupeReport,
) -> dict[str, str]:
    """Keep one phone per display name; lowest E.164 wins ties."""
    by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for phone, name in registry.items():
        by_name[name.casefold()].append((phone, name))

    collapsed: dict[str, str] = {}
    for entries in by_name.values():
        entries.sort(key=lambda item: item[0])
        winner_phone, winner_name = entries[0]
        collapsed[winner_phone] = winner_name
        for phone, name in entries[1:]:
            report.collapsed_name_dupes.append((name, phone, winner_phone))
    return collapsed


def ingest_vcards_to_registry(
    registry: dict[str, str],
    vcards: list,
    default_region: str,
    report: DedupeReport,
) -> None:
    for vcard in vcards:
        phones = vcard_phones(vcard, default_region)
        if not phones:
            report.skipped_no_phone += 1
            continue
        name = contact_name(vcard)
        for phone in phones:
            if not is_named_contact(name, [phone]):
                report.skipped_invalid_name += 1
                continue
            existing = registry.get(phone)
            if existing is None:
                registry[phone] = name
                continue
            if existing.casefold() == name.casefold():
                continue
            chosen = pick_better_name(existing, name)
            if chosen != existing:
                report.name_conflicts.append((phone, existing, name))
            registry[phone] = chosen


def registry_to_vcards(registry: dict[str, str], *, sms_tag: bool = False) -> list:
    vcards = []
    for phone in sorted(registry):
        vcard = vobject.vCard()
        vcard.add("fn").value = tagged_vcard_name(registry[phone], sms_tag=sms_tag)
        vcard.add("tel").value = phone
        vcards.append(vcard)
    return vcards


def dedupe_vcards(
    vcards: list,
    default_region: str,
    *,
    sms_tag: bool = False,
    one_name_one_phone: bool = True,
) -> tuple[list, DedupeReport]:
    """One named contact per E.164 phone; drop unknown and group-style labels."""
    report = DedupeReport(input_vcards=len(vcards))
    registry: dict[str, str] = {}
    ingest_vcards_to_registry(registry, vcards, default_region, report)
    if one_name_one_phone:
        registry = collapse_one_name_one_phone(registry, report)
    report.output_contacts = len(registry)
    return registry_to_vcards(registry, sms_tag=sms_tag), report


def print_dedupe_report(report: DedupeReport, path: Path) -> None:
    print(f"VCF: {path}")
    print(f"  Input vCards:         {report.input_vcards}")
    print(f"  Output contacts:      {report.output_contacts}")
    print(f"  Skipped (no phone):   {report.skipped_no_phone}")
    print(f"  Skipped (bad name):   {report.skipped_invalid_name}")
    if report.name_conflicts:
        print(f"  Name conflicts:       {len(report.name_conflicts)}")
        for phone, old, new in report.name_conflicts[:15]:
            print(f"    {phone}: {old!r} -> {pick_better_name(old, new)!r}")
        if len(report.name_conflicts) > 15:
            print(f"    ... and {len(report.name_conflicts) - 15} more")
    if report.collapsed_name_dupes:
        print(f"  Same name, extra phone:{len(report.collapsed_name_dupes)}")
        for name, dropped, kept in report.collapsed_name_dupes[:10]:
            print(f"    {name!r}: dropped {dropped}, kept {kept}")
        if len(report.collapsed_name_dupes) > 10:
            print(f"    ... and {len(report.collapsed_name_dupes) - 10} more")


@dataclass
class MergeReport:
    base_vcards: int = 0
    secondary_vcards: int = 0
    base_phones: int = 0
    secondary_phones: int = 0
    overlap: list[tuple[str, str, str]] = field(default_factory=list)
    overlap_same_name: int = 0
    overlap_name_conflict: int = 0
    to_add: list[tuple[str, str]] = field(default_factory=list)
    skipped_secondary: int = 0
    skipped_no_phone: int = 0
    skipped_number_only: int = 0


def analyze_vcf_merge(
    base_registry: dict[str, str],
    secondary_vcards: list,
    default_region: str,
    *,
    base_vcard_count: int,
) -> MergeReport:
    """Compare deduped base registry to secondary vCards."""
    report = MergeReport(
        base_vcards=base_vcard_count,
        secondary_vcards=len(secondary_vcards),
        base_phones=len(base_registry),
    )

    secondary_phones: set[str] = set()
    for vcard in secondary_vcards:
        secondary_phones.update(vcard_phones(vcard, default_region))
    report.secondary_phones = len(secondary_phones)

    for phone in sorted(secondary_phones):
        if phone not in base_registry:
            continue
        secondary_name = ""
        for vcard in secondary_vcards:
            phones = vcard_phones(vcard, default_region)
            if phone in phones:
                secondary_name = contact_name(vcard)
                break
        base_name = base_registry[phone]
        report.overlap.append((phone, base_name, secondary_name))
        if base_name.casefold() == secondary_name.casefold():
            report.overlap_same_name += 1
        else:
            report.overlap_name_conflict += 1

    known = set(base_registry)
    for vcard in secondary_vcards:
        phones = vcard_phones(vcard, default_region)
        if not phones:
            report.skipped_no_phone += 1
            continue
        if any(phone in known for phone in phones):
            report.skipped_secondary += 1
            continue
        name = contact_name(vcard)
        if not is_named_contact(name, phones):
            report.skipped_number_only += 1
            continue
        for phone in phones:
            report.to_add.append((phone, name))
            known.add(phone)

    return report


def merge_vcards(
    base_vcards: list,
    secondary_vcards: list,
    default_region: str,
    *,
    sms_tag: bool = False,
    one_name_one_phone: bool = True,
) -> tuple[list, MergeReport]:
    """Merge to one named contact per phone; base wins on overlap."""
    registry: dict[str, str] = {}
    base_dedupe = DedupeReport(input_vcards=len(base_vcards))
    ingest_vcards_to_registry(registry, base_vcards, default_region, base_dedupe)

    report = analyze_vcf_merge(
        registry,
        secondary_vcards,
        default_region,
        base_vcard_count=len(base_vcards),
    )

    for phone, name in report.to_add:
        registry[phone] = name

    if one_name_one_phone:
        collapse_report = DedupeReport()
        registry = collapse_one_name_one_phone(registry, collapse_report)

    return registry_to_vcards(registry, sms_tag=sms_tag), report


@dataclass
class SubtractReport:
    base_vcards: int = 0
    exclude_vcards: int = 0
    exclude_phones: int = 0
    removed: list[tuple[str, list[str]]] = field(default_factory=list)
    kept_vcards: int = 0
    skipped_invalid_name: int = 0
    collapsed_name_dupes: int = 0


def analyze_vcf_subtract(
    base_vcards: list,
    exclude_vcards: list,
    default_region: str,
) -> SubtractReport:
    report = SubtractReport(
        base_vcards=len(base_vcards),
        exclude_vcards=len(exclude_vcards),
    )
    exclude_phones: set[str] = set()
    for vcard in exclude_vcards:
        exclude_phones.update(vcard_phones(vcard, default_region))
    report.exclude_phones = len(exclude_phones)

    for vcard in base_vcards:
        phones = vcard_phones(vcard, default_region)
        if phones and any(phone in exclude_phones for phone in phones):
            report.removed.append((contact_name(vcard), phones))
        else:
            report.kept_vcards += 1

    return report


def subtract_vcards(
    base_vcards: list,
    exclude_vcards: list,
    default_region: str,
    *,
    sms_tag: bool = False,
    one_name_one_phone: bool = True,
) -> tuple[list, SubtractReport]:
    report = analyze_vcf_subtract(base_vcards, exclude_vcards, default_region)
    exclude_phones: set[str] = set()
    for vcard in exclude_vcards:
        exclude_phones.update(vcard_phones(vcard, default_region))

    kept_raw: list = []
    for vcard in base_vcards:
        phones = vcard_phones(vcard, default_region)
        if phones and any(phone in exclude_phones for phone in phones):
            continue
        kept_raw.append(vcard)

    kept, dedupe = dedupe_vcards(
        kept_raw,
        default_region,
        sms_tag=sms_tag,
        one_name_one_phone=one_name_one_phone,
    )
    report.kept_vcards = len(kept)
    report.skipped_invalid_name = dedupe.skipped_invalid_name
    report.collapsed_name_dupes = len(dedupe.collapsed_name_dupes)
    return kept, report


def print_subtract_report(
    report: SubtractReport,
    base_path: Path,
    exclude_path: Path,
) -> None:
    print(f"Base:    {base_path}")
    print(f"Exclude: {exclude_path}")
    print(f"  Base vCards:      {report.base_vcards}")
    print(f"  Exclude vCards:   {report.exclude_vcards}")
    print(f"  Exclude phones:   {report.exclude_phones}")
    print(f"  Removed vCards:   {len(report.removed)}")
    print(f"  Kept vCards:      {report.kept_vcards}")
    if report.skipped_invalid_name:
        print(f"  Skipped (bad name): {report.skipped_invalid_name}")
    if report.collapsed_name_dupes:
        print(f"  Same name, extra phone:{report.collapsed_name_dupes}")

    if report.removed:
        print("\nRemoved contacts:")
        for name, phones in report.removed[:25]:
            phone_list = ", ".join(phones)
            print(f"  {name}: {phone_list}")
        if len(report.removed) > 25:
            print(f"  ... and {len(report.removed) - 25} more")


def print_merge_report(
    report: MergeReport,
    base_path: Path,
    secondary_path: Path,
    *,
    base_label: str | None = None,
) -> None:
    print(f"Base:      {base_label or base_path}")
    print(f"Secondary: {secondary_path}")
    print(f"  Base vCards:          {report.base_vcards}")
    print(f"  Secondary vCards:     {report.secondary_vcards}")
    print(f"  Base phones:          {report.base_phones}")
    print(f"  Secondary phones:     {report.secondary_phones}")
    print(f"  Overlap (same phone): {len(report.overlap)}")
    print(f"    Same name:          {report.overlap_same_name}")
    print(f"    Name conflict:      {report.overlap_name_conflict}")
    print(f"  To add from secondary:{len(report.to_add)}")
    print(f"  Skipped (duplicate):  {report.skipped_secondary}")
    print(f"  Skipped (no phone):   {report.skipped_no_phone}")
    print(f"  Skipped (number only):{report.skipped_number_only}")

    if report.overlap_name_conflict:
        print("\nOverlap with different names (base kept on merge):")
        conflicts = [
            (phone, base_name, secondary_name)
            for phone, base_name, secondary_name in report.overlap
            if base_name.casefold() != secondary_name.casefold()
        ]
        for phone, base_name, secondary_name in conflicts[:15]:
            print(f"  {phone}: {base_name!r} (base) vs {secondary_name!r} (secondary)")
        if len(conflicts) > 15:
            print(f"  ... and {len(conflicts) - 15} more")

    if report.to_add:
        print("\nNew contacts to add:")
        for phone, name in report.to_add[:25]:
            print(f"  {phone}: {name}")
        if len(report.to_add) > 25:
            print(f"  ... and {len(report.to_add) - 25} more")


@dataclass
class ValidationReport:
    total_tel: int = 0
    already_standard: int = 0
    normalized: int = 0
    invalid: list[tuple[str, str]] = field(default_factory=list)
    cross_card_duplicates: dict[str, list[str]] = field(default_factory=dict)
    changes: list[tuple[str, str, str]] = field(default_factory=list)


def validate_vcards(vcards: list, default_region: str, apply: bool = False) -> ValidationReport:
    report = ValidationReport()
    number_to_contacts: dict[str, list[str]] = defaultdict(list)

    for vcard in vcards:
        name = contact_name(vcard)
        seen_on_card: set[str] = set()

        for tel in vcard.contents.get("tel", []):
            report.total_tel += 1
            raw = tel.value
            normalized = normalize_phone_number(raw, default_region)

            if not normalized:
                report.invalid.append((name, raw))
                continue

            if raw == normalized:
                report.already_standard += 1
            else:
                report.normalized += 1
                report.changes.append((name, raw, normalized))
                if apply:
                    tel.value = normalized

            if normalized in seen_on_card:
                continue
            seen_on_card.add(normalized)
            number_to_contacts[normalized].append(name)

    for number, names in sorted(number_to_contacts.items()):
        unique_names = list(dict.fromkeys(names))
        if len(unique_names) > 1:
            report.cross_card_duplicates[number] = unique_names

    return report


def load_vcards(path: Path) -> list:
    text = path.read_text(encoding="utf-8")
    return list(vobject.readComponents(text))


def write_vcards(path: Path, vcards: list) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for vcard in vcards:
            fh.write(vcard.serialize())


def print_report(report: ValidationReport, vcf_path: Path) -> int:
    print(f"VCF: {vcf_path}")
    print(f"  TEL entries:        {report.total_tel}")
    print(f"  Already E.164:      {report.already_standard}")
    print(f"  Would normalize:    {report.normalized}")
    print(f"  Invalid/unparsed:   {len(report.invalid)}")
    print(f"  Cross-card dupes:   {len(report.cross_card_duplicates)}")

    if report.changes:
        print("\nNormalization changes:")
        for name, raw, normalized in report.changes:
            print(f"  {name}: {raw!r} -> {normalized}")

    if report.invalid:
        print("\nInvalid phone numbers:")
        for name, raw in report.invalid:
            print(f"  {name}: {raw!r}")

    if report.cross_card_duplicates:
        print("\nSame number on multiple contacts:")
        for number, names in report.cross_card_duplicates.items():
            print(f"  {number}: {', '.join(names)}")

    if report.invalid:
        return 1
    return 0
