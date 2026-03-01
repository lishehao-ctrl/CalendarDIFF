from __future__ import annotations

from email.utils import parseaddr


def is_valid_email_address(value: str | None) -> bool:
    if value is None:
        return False
    candidate = value.strip()
    if not candidate:
        return False
    if any(ch.isspace() for ch in candidate):
        return False

    _, parsed = parseaddr(candidate)
    if parsed != candidate:
        return False

    local, separator, domain = candidate.rpartition("@")
    if separator != "@":
        return False
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    if domain.startswith(".") or domain.endswith("."):
        return False
    if ".." in domain:
        return False
    return True
