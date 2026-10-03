"""PII (Personally Identifiable Information) Anonymizer and Data Privacy Guardrail.

Protects sensitive personal data (citizen ID / CCCD, phone numbers, bank accounts, emails)
in compliance with Vietnam Personal Data Protection Decree No. 13/2023/ND-CP before
persistence into database or telemetry tracing.
"""

from __future__ import annotations

import re
from typing import Any

# CCCD (12 digits) or legacy CMND (9 digits)
_CCCD_PATTERN = re.compile(r"\b(?:\d{12}|\d{9})\b")

# Vietnamese phone numbers: starts with 03, 05, 07, 08, 09 (10 digits) or +84...
_PHONE_PATTERN = re.compile(r"(?:\+84|0)(?:3[2-9]|5[689]|7[06-9]|8[1-9]|9\d)\d{7}\b")

# Email address
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

# Bank account numbers: preceded by context keywords
_BANK_ACCOUNT_PATTERN = re.compile(
    r"\b(?:stk|số tài khoản|tài khoản|tk)\s*(?:số|:|\s)\s*(\d{8,16})\b",
    re.IGNORECASE,
)


def mask_cccd(match: re.Match[str]) -> str:
    val = match.group(0)
    if len(val) == 12:
        return f"{val[:3]}******{val[-3:]}"
    return f"{val[:2]}*****{val[-2:]}"


def mask_phone(match: re.Match[str]) -> str:
    val = match.group(0)
    if len(val) >= 10:
        return f"{val[:3]}****{val[-3:]}"
    return f"{val[:2]}***{val[-2:]}"


def mask_email(match: re.Match[str]) -> str:
    val = match.group(0)
    parts = val.split("@")
    if len(parts) == 2:
        user, domain = parts
        masked_user = f"{user[0]}***" if len(user) > 1 else "*"
        return f"{masked_user}@{domain}"
    return "[ĐÃ_ẨN_EMAIL]"


def mask_bank_account(match: re.Match[str]) -> str:
    full = match.group(0)
    acc = match.group(1)
    masked_acc = f"****{acc[-4:]}" if len(acc) >= 4 else "****"
    return full.replace(acc, masked_acc)


def anonymize_text(text: str) -> str:
    """Mask sensitive PII in raw text while preserving linguistic context."""
    if not text or not isinstance(text, str):
        return text

    masked = _CCCD_PATTERN.sub(mask_cccd, text)
    masked = _PHONE_PATTERN.sub(mask_phone, masked)
    masked = _EMAIL_PATTERN.sub(mask_email, masked)
    masked = _BANK_ACCOUNT_PATTERN.sub(mask_bank_account, masked)
    return masked


def has_pii(text: str) -> bool:
    """Return True if any high-confidence PII is detected in text."""
    if not text or not isinstance(text, str):
        return False
    return bool(
        _CCCD_PATTERN.search(text)
        or _PHONE_PATTERN.search(text)
        or _EMAIL_PATTERN.search(text)
    )


def anonymize_payload(data: Any) -> Any:
    """Recursively mask PII in nested dicts, lists, and string fields."""
    if isinstance(data, str):
        return anonymize_text(data)
    if isinstance(data, dict):
        return {k: anonymize_payload(v) for k, v in data.items()}
    if isinstance(data, list):
        return [anonymize_payload(item) for item in data]
    return data
