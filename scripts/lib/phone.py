"""Phone normalization and contact-name heuristics for VCF tools."""

from __future__ import annotations

import re

import phonenumbers

AND_OTHERS_SUFFIX_RE = re.compile(r", and \d+ others$")
GROUP_PREFIX = "Group chat - "
_NON_NAME_LABELS = frozenset({"me", "unknown", "(unnamed)"})
_LABEL_NOISE_RE = re.compile(r"[^\w\s]")
_DIGITS_ONLY_RE = re.compile(r"\D")


def _normalized_label(name: str) -> str:
    return _LABEL_NOISE_RE.sub("", name).casefold().strip()


def is_group_style_name(name: str) -> bool:
    """True for MMS group titles and other multi-party labels, not 1:1 contacts."""
    cleaned = " ".join((name or "").split())
    if not cleaned:
        return False
    if cleaned.startswith(GROUP_PREFIX):
        return True
    if AND_OTHERS_SUFFIX_RE.search(cleaned):
        return True
    return cleaned.count(", ") >= 2


def is_named_contact(name: str, phones: list[str] | None = None) -> bool:
    """True when display name is a real 1:1 contact, not a bare phone or group label."""
    cleaned = " ".join((name or "").split())
    if not cleaned or cleaned.casefold() in _NON_NAME_LABELS:
        return False
    if _normalized_label(cleaned) in {"unknown", "unnamed", "null", "none"}:
        return False
    if is_group_style_name(cleaned):
        return False
    if cleaned.isdigit():
        return False
    name_digits = _DIGITS_ONLY_RE.sub("", cleaned)
    for phone in phones or ():
        if cleaned == phone:
            return False
        phone_digits = _DIGITS_ONLY_RE.sub("", phone)
        if name_digits and name_digits == phone_digits:
            return False
    return True


def normalize_phone_number(raw_phone: str, default_region: str) -> str | None:
    if not raw_phone or not raw_phone.strip():
        return None

    raw_phone = raw_phone.strip()
    try:
        phone_number = phonenumbers.parse(raw_phone, None)
    except phonenumbers.NumberParseException:
        try:
            phone_number = phonenumbers.parse(raw_phone, default_region)
        except phonenumbers.NumberParseException:
            return None

    if not phonenumbers.is_valid_number(phone_number):
        return None

    return phonenumbers.format_number(phone_number, phonenumbers.PhoneNumberFormat.E164)
