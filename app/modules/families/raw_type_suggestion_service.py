from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.common.course_identity import course_display_name
from app.modules.families.raw_type_service import list_raw_type_suggestions


def list_raw_type_suggestion_items(
    db: Session,
    *,
    user_id: int,
    status: str | None,
    course_dept: str | None,
    course_number: int | None,
    course_suffix: str | None,
    course_quarter: str | None,
    course_year2: int | None,
    limit: int,
    offset: int,
) -> list[dict]:
    rows = list_raw_type_suggestions(
        db,
        user_id=user_id,
        status=status,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
        limit=limit,
        offset=offset,
    )
    out: list[dict] = []
    for row in rows:
        source_raw_type = row.source_raw_type
        suggested_raw_type = row.suggested_raw_type
        out.append(
            {
                "id": row.id,
                "course_display": course_display_name(
                    course_dept=source_raw_type.family.course_dept if source_raw_type is not None and source_raw_type.family is not None else None,
                    course_number=source_raw_type.family.course_number if source_raw_type is not None and source_raw_type.family is not None else None,
                    course_suffix=source_raw_type.family.course_suffix if source_raw_type is not None and source_raw_type.family is not None else None,
                    course_quarter=source_raw_type.family.course_quarter if source_raw_type is not None and source_raw_type.family is not None else None,
                    course_year2=source_raw_type.family.course_year2 if source_raw_type is not None and source_raw_type.family is not None else None,
                )
                or "Unknown",
                "course_dept": source_raw_type.family.course_dept if source_raw_type is not None and source_raw_type.family is not None else "",
                "course_number": source_raw_type.family.course_number if source_raw_type is not None and source_raw_type.family is not None else 0,
                "course_suffix": source_raw_type.family.course_suffix if source_raw_type is not None and source_raw_type.family is not None else None,
                "course_quarter": source_raw_type.family.course_quarter if source_raw_type is not None and source_raw_type.family is not None else None,
                "course_year2": source_raw_type.family.course_year2 if source_raw_type is not None and source_raw_type.family is not None else None,
                "status": row.status.value if hasattr(row.status, 'value') else str(row.status),
                "confidence": float(row.confidence),
                "evidence": row.evidence,
                "source_observation_id": row.source_observation_id,
                "source_raw_type": source_raw_type.raw_type if source_raw_type is not None else None,
                "source_raw_type_id": source_raw_type.id if source_raw_type is not None else None,
                "source_family_id": source_raw_type.family_id if source_raw_type is not None else None,
                "source_family_name": source_raw_type.family.canonical_label if source_raw_type is not None and source_raw_type.family is not None else None,
                "suggested_raw_type": suggested_raw_type.raw_type if suggested_raw_type is not None else None,
                "suggested_raw_type_id": suggested_raw_type.id if suggested_raw_type is not None else None,
                "suggested_family_id": suggested_raw_type.family_id if suggested_raw_type is not None else None,
                "suggested_family_name": suggested_raw_type.family.canonical_label if suggested_raw_type is not None and suggested_raw_type.family is not None else None,
                "review_note": row.review_note,
                "reviewed_at": row.reviewed_at,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
    return out
