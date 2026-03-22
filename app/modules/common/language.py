from __future__ import annotations

from typing import Literal


LanguageCodeLiteral = Literal["en", "zh-CN"]
SUPPORTED_LANGUAGE_CODES: tuple[LanguageCodeLiteral, ...] = ("en", "zh-CN")
DEFAULT_LANGUAGE_CODE: LanguageCodeLiteral = "en"


def normalize_language_code(value: str) -> LanguageCodeLiteral:
    stripped = value.strip()
    if not stripped:
        raise ValueError("language_code must not be blank")
    lowered = stripped.lower()
    if lowered in {"en", "en-us", "en_us"}:
        return "en"
    if lowered in {"zh-cn", "zh_cn", "zh-hans-cn"}:
        return "zh-CN"
    raise ValueError("language_code must be one of: en, zh-CN")


__all__ = [
    "DEFAULT_LANGUAGE_CODE",
    "LanguageCodeLiteral",
    "SUPPORTED_LANGUAGE_CODES",
    "normalize_language_code",
]
