from __future__ import annotations

"""
Archived regex patterns removed from runtime on 2026-02-28.

This file is intentionally not imported by sync runtime code. It is retained as a
reference baseline for future rule-vs-LLM/BERT comparisons.
"""

NORMALIZER_REGEX_PATTERNS: dict[str, str] = {
    "SECTION_TAG_PATTERN": r"\[([A-Z]{2,6}\d{1,4}[A-Z]?)(?:_[A-Z0-9]+){1,4}\]",
    "SUMMARY_COURSE_PATTERN": r"\b([A-Z]{2,6})\s?(\d{1,4}[A-Z]?)\b",
    "COMPACT_COURSE_PATTERN": r"^([A-Z]{2,6})(\d{1,4}[A-Z]?)$",
    "DEADLINE_LIKE_PATTERN": (
        r"\b("
        r"assignment|homework|project|milestone|pset|lab|discussion|quiz|exam|test|midterm|final|"
        r"deadline|due|submit|deliverable|report|presentation"
        r")\b"
    ),
}


EMAIL_RULE_REGEX_PATTERNS: dict[str, str] = {
    "ISO_DT_RE": r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})\b",
    "SCHEDULE_TERMS_RE": (
        r"\b(schedule|reschedul|time change|location change|class moved|section moved|moved to|postponed|moved)\b"
    ),
    "DEADLINE_TERMS_RE": r"\b(deadline|due|submit by|extended|extension)\b",
    "EXAM_TERMS_RE": r"\b(quiz|midterm|final|exam|test)\b",
    "ASSIGNMENT_TERMS_RE": r"\b(homework|assignment|project|pset|lab)\b",
    "ACTION_TERMS_RE": (
        r"\b(required action|please submit|please complete|must|need to|reply|send your|fill out|register)\b"
    ),
    "COURSE_RE": r"\b([A-Z]{2,5})\s*-?\s*(\d{1,3}[A-Z]?)\b",
}


RUNTIME_MISC_REGEX_PATTERNS: dict[str, str] = {
    "USER_EMAIL_PATTERN": r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$",
    "LOG_REDACTION_URL_PATTERN": r"https?://[^\s]+",
}
