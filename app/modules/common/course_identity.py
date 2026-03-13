from __future__ import annotations

import re


_COURSE_DISPLAY_RE = re.compile(
    r"^\s*(?P<dept>[A-Za-z][A-Za-z0-9]*)\s+(?P<number>\d{1,4})(?P<suffix>[A-Za-z]{0,8})?(?:\s+(?P<quarter>WI|SP|SU|FA)(?P<year2>\d{2}))?\s*$",
    re.IGNORECASE,
)


def normalize_label_token(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    raw = raw.replace("-", " ").replace("_", " ")
    return " ".join(raw.split())[:128]


def normalize_course_identity(
    *,
    course_dept: str | None,
    course_number: int | None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
) -> dict[str, object]:
    dept = (course_dept or "").strip().upper()[:16] or None
    number = int(course_number) if isinstance(course_number, int) else None
    suffix = (course_suffix or "").strip().upper()[:8] or None
    quarter = (course_quarter or "").strip().upper()[:4] or None
    if quarter not in {"WI", "SP", "SU", "FA"}:
        quarter = None
    year2 = int(course_year2) if isinstance(course_year2, int) and 0 <= int(course_year2) <= 99 else None
    return {
        "course_dept": dept,
        "course_number": number,
        "course_suffix": suffix,
        "course_quarter": quarter,
        "course_year2": year2,
    }


def normalized_course_identity_key(
    *,
    course_dept: str | None,
    course_number: int | None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
) -> str:
    normalized = normalize_course_identity(
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
    )
    if not isinstance(normalized["course_dept"], str) or not isinstance(normalized["course_number"], int):
        return ""
    dept = normalize_label_token(normalized["course_dept"] if isinstance(normalized["course_dept"], str) else None)
    number = str(normalized["course_number"]) if isinstance(normalized["course_number"], int) else ""
    suffix = normalize_label_token(normalized["course_suffix"] if isinstance(normalized["course_suffix"], str) else None)
    quarter = normalize_label_token(normalized["course_quarter"] if isinstance(normalized["course_quarter"], str) else None)
    year2 = f"{normalized['course_year2']:02d}" if isinstance(normalized["course_year2"], int) else ""
    return "|".join([dept, number, suffix, quarter, year2])


def course_display_name(
    *,
    course_dept: str | None = None,
    course_number: int | None = None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
    semantic_event: dict | None = None,
    course_parse: dict | None = None,
) -> str | None:
    source = semantic_event if isinstance(semantic_event, dict) else course_parse if isinstance(course_parse, dict) else {}
    dept = course_dept if course_dept is not None else source.get("course_dept") if semantic_event else source.get("dept")
    number = course_number if course_number is not None else source.get("course_number") if semantic_event else source.get("number")
    suffix = course_suffix if course_suffix is not None else source.get("course_suffix") if semantic_event else source.get("suffix")
    quarter = course_quarter if course_quarter is not None else source.get("course_quarter") if semantic_event else source.get("quarter")
    year2 = course_year2 if course_year2 is not None else source.get("course_year2") if semantic_event else source.get("year2")
    normalized = normalize_course_identity(
        course_dept=dept if isinstance(dept, str) else None,
        course_number=number if isinstance(number, int) else None,
        course_suffix=suffix if isinstance(suffix, str) else None,
        course_quarter=quarter if isinstance(quarter, str) else None,
        course_year2=year2 if isinstance(year2, int) else None,
    )
    display_dept = normalized["course_dept"]
    display_number = normalized["course_number"]
    if not isinstance(display_dept, str) or not isinstance(display_number, int):
        return None
    base = f"{display_dept} {display_number}{normalized['course_suffix'] or ''}".strip()
    if isinstance(normalized["course_quarter"], str) and isinstance(normalized["course_year2"], int):
        return f"{base} {normalized['course_quarter']}{normalized['course_year2']:02d}"[:64]
    return base[:64]


def parse_course_display(value: str | None) -> dict[str, object]:
    raw = (value or "").strip()
    if not raw:
        return normalize_course_identity(course_dept=None, course_number=None)
    match = _COURSE_DISPLAY_RE.match(raw)
    if match is None:
        return normalize_course_identity(course_dept=None, course_number=None)
    year2 = match.group("year2")
    return normalize_course_identity(
        course_dept=match.group("dept"),
        course_number=int(match.group("number")),
        course_suffix=match.group("suffix") or None,
        course_quarter=match.group("quarter") or None,
        course_year2=int(year2) if year2 else None,
    )


def course_identity_matches(left: object, right: object) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return normalized_course_identity_key(
        course_dept=left.get("course_dept") if isinstance(left.get("course_dept"), str) else None,
        course_number=left.get("course_number") if isinstance(left.get("course_number"), int) else None,
        course_suffix=left.get("course_suffix") if isinstance(left.get("course_suffix"), str) else None,
        course_quarter=left.get("course_quarter") if isinstance(left.get("course_quarter"), str) else None,
        course_year2=left.get("course_year2") if isinstance(left.get("course_year2"), int) else None,
    ) == normalized_course_identity_key(
        course_dept=right.get("course_dept") if isinstance(right.get("course_dept"), str) else None,
        course_number=right.get("course_number") if isinstance(right.get("course_number"), int) else None,
        course_suffix=right.get("course_suffix") if isinstance(right.get("course_suffix"), str) else None,
        course_quarter=right.get("course_quarter") if isinstance(right.get("course_quarter"), str) else None,
        course_year2=right.get("course_year2") if isinstance(right.get("course_year2"), int) else None,
    )


__all__ = [
    "course_display_name",
    "course_identity_matches",
    "normalize_course_identity",
    "normalize_label_token",
    "normalized_course_identity_key",
    "parse_course_display",
]
