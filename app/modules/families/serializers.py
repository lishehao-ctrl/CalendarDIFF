from __future__ import annotations

from app.modules.common.course_identity import course_display_name
from app.modules.families.schemas import CourseRawTypeResponse, CourseWorkItemFamilyResponse


def course_identity_response_payload(
    *,
    course_dept: str,
    course_number: int,
    course_suffix: str | None,
    course_quarter: str | None,
    course_year2: int | None,
) -> dict[str, object]:
    return {
        "course_display": course_display_name(
            course_dept=course_dept,
            course_number=course_number,
            course_suffix=course_suffix,
            course_quarter=course_quarter,
            course_year2=course_year2,
        )
        or "Unknown",
        "course_dept": course_dept,
        "course_number": course_number,
        "course_suffix": course_suffix,
        "course_quarter": course_quarter,
        "course_year2": course_year2,
    }


def to_course_family_response(row) -> CourseWorkItemFamilyResponse:
    raw_types = []
    if hasattr(row, "raw_types") and isinstance(row.raw_types, list):
        for item in row.raw_types:
            raw = getattr(item, "raw_type", None)
            if isinstance(raw, str) and raw.strip():
                raw_types.append(raw)
    seen = set()
    deduped_raw_types = []
    for item in raw_types:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped_raw_types.append(item)
    return CourseWorkItemFamilyResponse(
        id=row.id,
        canonical_label=row.canonical_label,
        raw_types=deduped_raw_types,
        created_at=row.created_at,
        updated_at=row.updated_at,
        **course_identity_response_payload(
            course_dept=row.course_dept,
            course_number=row.course_number,
            course_suffix=row.course_suffix,
            course_quarter=row.course_quarter,
            course_year2=row.course_year2,
        ),
    )


def to_course_raw_type_response(row) -> CourseRawTypeResponse:
    family = row.family
    return CourseRawTypeResponse(
        id=row.id,
        family_id=row.family_id,
        raw_type=row.raw_type,
        created_at=row.created_at,
        updated_at=row.updated_at,
        **course_identity_response_payload(
            course_dept=family.course_dept if family is not None else "",
            course_number=family.course_number if family is not None else 0,
            course_suffix=family.course_suffix if family is not None else None,
            course_quarter=family.course_quarter if family is not None else None,
            course_year2=family.course_year2 if family is not None else None,
        ),
    )


__all__ = [
    "course_identity_response_payload",
    "to_course_family_response",
    "to_course_raw_type_response",
]
