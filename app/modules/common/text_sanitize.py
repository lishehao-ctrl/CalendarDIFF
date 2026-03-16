from __future__ import annotations

import re
from html import unescape

_HTML_BREAK_RE = re.compile(r"(?i)<(?:br|/p|/div|/li|/tr|/h[1-6])[^>]*>")
_HTML_TAG_RE = re.compile(r"(?s)<[^>]+>")
_HTML_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1>")
_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINE_RE = re.compile(r"\n{3,}")


def sanitize_markup_text(value: str | None, *, max_length: int | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    text = _HTML_SCRIPT_STYLE_RE.sub(" ", text)
    text = _HTML_BREAK_RE.sub("\n", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = unescape(text)
    text = text.replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE_RE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = _BLANK_LINE_RE.sub("\n\n", text)
    cleaned = text.strip()
    if not cleaned:
        return None
    if isinstance(max_length, int) and max_length > 0:
        return cleaned[:max_length]
    return cleaned


__all__ = ["sanitize_markup_text"]
