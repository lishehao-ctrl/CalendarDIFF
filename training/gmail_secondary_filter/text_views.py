from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

_TARGET_MARKERS = (
    "due", "deadline", "exam", "midterm", "final", "quiz", "homework",
    "assignment", "project", "gradescope", "piazza", "released",
    "updated", "changed", "moved", "rescheduled", "regrade",
)
_TIME_MARKERS = (
    "am", "pm", "midnight", "tonight", "tomorrow", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday",
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
    "oct", "nov", "dec",
)
_NON_TARGET_MARKERS = (
    "digest", "newsletter", "tracking", "shipping", "delivery", "subscription",
    "recruiting", "career", "internship", "unsubscribe", "manage preferences",
    "view in browser", "no monitored deadline changed", "unchanged", "wrapper",
)
_QUOTE_MARKERS = ("forwarded message", "original message", " wrote:", "from:", "sent:", "to:", "subject:")


def build_text_view(row: dict, *, view: str) -> str:
    normalized_view = view.strip().lower()
    if normalized_view in {"v1", "compact_v1", "distil_v1"}:
        return build_compact_v1_text(row)
    if normalized_view in {"compact_v2", "distil_v2"}:
        return build_compact_v2_text(row)
    if normalized_view in {"v2", "long_v2", "modernbert_v2"}:
        return build_long_v2_text(row)
    raise ValueError(f"Unsupported text view: {view}")


def build_compact_v1_text(row: dict) -> str:
    from_header = str(row.get("from_header") or "")
    subject = str(row.get("subject") or "")
    snippet = str(row.get("snippet") or "")
    body_text = str(row.get("body_text") or "")
    known_course_tokens = row.get("known_course_tokens") or []
    course_text = " | ".join(str(item) for item in known_course_tokens if isinstance(item, str))
    return "\n".join(
        [
            f"FROM: {from_header}",
            f"SUBJECT: {subject}",
            f"SNIPPET: {snippet}",
            f"KNOWN_COURSE_TOKENS: {course_text}",
            f"BODY: {body_text}",
        ]
    )


def build_compact_v2_text(row: dict) -> str:
    from_header = _normalize_text(row.get("from_header"), max_chars=180)
    subject = _normalize_text(row.get("subject"), max_chars=220)
    snippet = _normalize_text(row.get("snippet"), max_chars=320)
    known_course_tokens = row.get("known_course_tokens") or []
    body_text = _normalize_text(row.get("body_text"), max_chars=4000)
    body_sentences = _top_salient_sentences(body_text, budget_chars=720)
    course_text = " | ".join(str(item) for item in known_course_tokens if isinstance(item, str))
    parts = [f"FROM: {from_header}", f"SUBJECT: {subject}"]
    if course_text:
        parts.append(f"KNOWN_COURSE_TOKENS: {course_text}")
    if snippet:
        parts.append(f"SNIPPET: {snippet}")
    if body_sentences:
        parts.append(f"SALIENT_BODY: {' | '.join(body_sentences)}")
    return "\n".join(parts)


def build_long_v2_text(row: dict) -> str:
    from_header = _normalize_text(row.get("from_header"), max_chars=240)
    subject = _normalize_text(row.get("subject"), max_chars=260)
    snippet = _normalize_text(row.get("snippet"), max_chars=480)
    body_text = _normalize_text(row.get("body_text"), max_chars=6000)
    known_course_tokens = row.get("known_course_tokens") or []
    label_ids = row.get("label_ids") or []
    course_text = " | ".join(str(item) for item in known_course_tokens if isinstance(item, str))
    label_text = ", ".join(str(item) for item in label_ids if isinstance(item, str))
    parts = [f"FROM: {from_header}", f"SUBJECT: {subject}"]
    if label_text:
        parts.append(f"LABELS: {label_text}")
    if course_text:
        parts.append(f"KNOWN_COURSE_TOKENS: {course_text}")
    if snippet:
        parts.append(f"SNIPPET: {snippet}")
    if body_text:
        parts.append(f"BODY: {body_text}")
    return "\n".join(parts)


def _top_salient_sentences(body_text: str, *, budget_chars: int) -> list[str]:
    raw_sentences = [part.strip() for part in _SENTENCE_SPLIT_RE.split(body_text) if part.strip()]
    scored = []
    for index, sentence in enumerate(raw_sentences):
        lowered = sentence.lower()
        score = 0
        if any(marker in lowered for marker in _TARGET_MARKERS):
            score += 5
        if any(marker in lowered for marker in _TIME_MARKERS):
            score += 4
        if any(marker in lowered for marker in _NON_TARGET_MARKERS):
            score += 3
        if any(marker in lowered for marker in _QUOTE_MARKERS):
            score -= 2
        if len(sentence) < 20:
            score -= 1
        if score <= 0:
            continue
        scored.append((score, -index, sentence))
    scored.sort(reverse=True)
    chosen = []
    used = 0
    for _score, _neg_index, sentence in scored:
        cost = len(sentence) + (3 if chosen else 0)
        if used + cost > budget_chars:
            continue
        chosen.append(sentence)
        used += cost
    if not chosen and raw_sentences:
        fallback = raw_sentences[0]
        chosen.append(fallback[: budget_chars - 3].rstrip() + "..." if len(fallback) > budget_chars else fallback)
    return chosen


def _normalize_text(value: object, *, max_chars: int) -> str:
    text = str(value or "")
    text = _URL_RE.sub("[url]", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if max_chars > 0 and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


__all__ = ["build_text_view", "build_compact_v1_text", "build_compact_v2_text", "build_long_v2_text"]
