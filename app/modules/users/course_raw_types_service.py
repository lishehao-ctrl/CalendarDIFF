from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.shared import CourseRawTypeSuggestion, CourseRawTypeSuggestionStatus, CourseWorkItemLabelFamily, CourseWorkItemRawType
from app.modules.common.course_identity import normalized_course_identity_key, parse_course_display
from app.modules.users.course_work_item_families_service import normalize_label_token


class CourseRawTypeValidationError(RuntimeError):
    pass


class CourseRawTypeNotFoundError(RuntimeError):
    pass


def list_course_raw_types(
    db: Session,
    *,
    user_id: int,
    course_key: str | None = None,
    course_dept: str | None = None,
    course_number: int | None = None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
    family_id: int | None = None,
) -> list[CourseWorkItemRawType]:
    identity = _coalesce_course_identity(
        course_key=course_key,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
    )
    stmt = (
        select(CourseWorkItemRawType)
        .join(CourseWorkItemLabelFamily, CourseWorkItemRawType.family_id == CourseWorkItemLabelFamily.id)
        .where(CourseWorkItemLabelFamily.user_id == user_id)
    )
    normalized_course = normalized_course_identity_key(
        **identity,
    )
    if normalized_course:
        stmt = stmt.where(CourseWorkItemLabelFamily.normalized_course_identity == normalized_course)
    if family_id is not None:
        stmt = stmt.where(CourseWorkItemRawType.family_id == family_id)
    stmt = stmt.order_by(
        CourseWorkItemLabelFamily.course_dept.asc(),
        CourseWorkItemLabelFamily.course_number.asc(),
        CourseWorkItemLabelFamily.course_suffix.asc(),
        CourseWorkItemRawType.raw_type.asc(),
        CourseWorkItemRawType.id.asc(),
    )
    return list(db.scalars(stmt).all())


def get_course_raw_type(db: Session, *, user_id: int, raw_type_id: int) -> CourseWorkItemRawType | None:
    return db.scalar(
        select(CourseWorkItemRawType)
        .join(CourseWorkItemLabelFamily, CourseWorkItemRawType.family_id == CourseWorkItemLabelFamily.id)
        .where(CourseWorkItemRawType.id == raw_type_id, CourseWorkItemLabelFamily.user_id == user_id)
        .limit(1)
    )


def find_course_raw_type(
    db: Session,
    *,
    user_id: int,
    course_key: str | None = None,
    course_dept: str | None,
    course_number: int | None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
    raw_type: str | None,
) -> CourseWorkItemRawType | None:
    identity = _coalesce_course_identity(
        course_key=course_key,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
    )
    normalized_course = normalized_course_identity_key(
        **identity,
    )
    normalized_raw_type = normalize_label_token(raw_type)
    if not normalized_course or not normalized_raw_type:
        return None
    return db.scalar(
        select(CourseWorkItemRawType)
        .join(CourseWorkItemLabelFamily, CourseWorkItemRawType.family_id == CourseWorkItemLabelFamily.id)
        .where(
            CourseWorkItemLabelFamily.user_id == user_id,
            CourseWorkItemLabelFamily.normalized_course_identity == normalized_course,
            CourseWorkItemRawType.normalized_raw_type == normalized_raw_type,
        )
        .limit(1)
    )


def create_course_raw_type(
    db: Session,
    *,
    family: CourseWorkItemLabelFamily,
    raw_type: str,
    metadata: dict[str, Any] | None = None,
    commit: bool = True,
) -> CourseWorkItemRawType:
    normalized_raw_type = normalize_label_token(raw_type)
    if not normalized_raw_type:
        raise CourseRawTypeValidationError("raw_type must not be blank")
    existing = find_course_raw_type(
        db,
        user_id=family.user_id,
        course_dept=family.course_dept,
        course_number=family.course_number,
        course_suffix=family.course_suffix,
        course_quarter=family.course_quarter,
        course_year2=family.course_year2,
        raw_type=normalized_raw_type,
    )
    if existing is not None:
        existing.family_id = family.id
        if metadata:
            payload = dict(existing.metadata_json) if isinstance(existing.metadata_json, dict) else {}
            payload.update(metadata)
            existing.metadata_json = payload
        if commit:
            db.commit()
            db.refresh(existing)
        return existing

    row = CourseWorkItemRawType(
        family_id=family.id,
        raw_type=raw_type.strip()[:128],
        normalized_raw_type=normalized_raw_type,
        metadata_json=dict(metadata or {}),
    )
    db.add(row)
    db.flush()
    if commit:
        db.commit()
        db.refresh(row)
    return row


def replace_family_raw_types(
    db: Session,
    *,
    family: CourseWorkItemLabelFamily,
    raw_types: list[str],
    commit: bool = True,
) -> CourseWorkItemLabelFamily:
    normalized_target = {normalize_label_token(value): value.strip()[:128] for value in raw_types if normalize_label_token(value)}
    existing_rows = list_course_raw_types(db, user_id=family.user_id, family_id=family.id)
    existing_by_norm = {row.normalized_raw_type: row for row in existing_rows}

    course_rows = list_course_raw_types(
        db,
        user_id=family.user_id,
        course_dept=family.course_dept,
        course_number=family.course_number,
        course_suffix=family.course_suffix,
        course_quarter=family.course_quarter,
        course_year2=family.course_year2,
    )
    course_by_norm = {row.normalized_raw_type: row for row in course_rows}

    for normalized, row in list(existing_by_norm.items()):
        if normalized not in normalized_target:
            db.delete(row)
    for normalized, raw in normalized_target.items():
        row = course_by_norm.get(normalized)
        if row is None:
            db.add(
                CourseWorkItemRawType(
                    family_id=family.id,
                    raw_type=raw,
                    normalized_raw_type=normalized,
                    metadata_json={},
                )
            )
        else:
            row.raw_type = raw
            row.family_id = family.id
    db.flush()
    if commit:
        db.commit()
        db.refresh(family)
    return family


def move_course_raw_type_to_family(
    db: Session,
    *,
    raw_type: CourseWorkItemRawType,
    family: CourseWorkItemLabelFamily,
    commit: bool = True,
) -> CourseWorkItemRawType:
    source_family = raw_type.family
    if source_family is None:
        raise CourseRawTypeValidationError("raw type must belong to a family")
    if source_family.user_id != family.user_id:
        raise CourseRawTypeValidationError("raw type and family must belong to same user")
    if source_family.normalized_course_identity != family.normalized_course_identity:
        raise CourseRawTypeValidationError("raw type and family must belong to same course")
    raw_type.family_id = family.id
    db.flush()
    if commit:
        db.commit()
        db.refresh(raw_type)
    return raw_type


def create_raw_type_suggestion(
    db: Session,
    *,
    source_raw_type: CourseWorkItemRawType,
    suggested_raw_type: CourseWorkItemRawType | None,
    source_observation_id: int | None,
    confidence: float,
    evidence: str | None,
) -> CourseRawTypeSuggestion:
    stmt = select(CourseRawTypeSuggestion).where(
        CourseRawTypeSuggestion.source_raw_type_id == source_raw_type.id,
        CourseRawTypeSuggestion.status == CourseRawTypeSuggestionStatus.PENDING,
    )
    existing = db.scalar(stmt.limit(1))
    if existing is not None:
        existing.suggested_raw_type_id = suggested_raw_type.id if suggested_raw_type is not None else None
        existing.confidence = confidence
        existing.evidence = evidence[:255] if isinstance(evidence, str) and evidence.strip() else None
        db.flush()
        return existing
    row = CourseRawTypeSuggestion(
        source_raw_type_id=source_raw_type.id,
        suggested_raw_type_id=suggested_raw_type.id if suggested_raw_type is not None else None,
        source_observation_id=source_observation_id,
        status=CourseRawTypeSuggestionStatus.PENDING,
        confidence=max(0.0, min(1.0, float(confidence))),
        evidence=evidence[:255] if isinstance(evidence, str) and evidence.strip() else None,
    )
    db.add(row)
    db.flush()
    return row


def list_raw_type_suggestions(
    db: Session,
    *,
    user_id: int,
    status: str | None = None,
    course_key: str | None = None,
    course_dept: str | None = None,
    course_number: int | None = None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CourseRawTypeSuggestion]:
    identity = _coalesce_course_identity(
        course_key=course_key,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
    )
    stmt = (
        select(CourseRawTypeSuggestion)
        .join(CourseWorkItemRawType, CourseRawTypeSuggestion.source_raw_type_id == CourseWorkItemRawType.id)
        .join(CourseWorkItemLabelFamily, CourseWorkItemRawType.family_id == CourseWorkItemLabelFamily.id)
        .where(CourseWorkItemLabelFamily.user_id == user_id)
    )
    normalized_status = (status or "").strip().lower()
    if normalized_status:
        stmt = stmt.where(CourseRawTypeSuggestion.status == normalized_status)
    normalized_course = normalized_course_identity_key(
        **identity,
    )
    if normalized_course:
        stmt = stmt.where(CourseWorkItemLabelFamily.normalized_course_identity == normalized_course)
    stmt = stmt.order_by(CourseRawTypeSuggestion.created_at.desc(), CourseRawTypeSuggestion.id.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt).all())


def get_raw_type_suggestion(db: Session, *, user_id: int, suggestion_id: int) -> CourseRawTypeSuggestion | None:
    return db.scalar(
        select(CourseRawTypeSuggestion)
        .join(CourseWorkItemRawType, CourseRawTypeSuggestion.source_raw_type_id == CourseWorkItemRawType.id)
        .join(CourseWorkItemLabelFamily, CourseWorkItemRawType.family_id == CourseWorkItemLabelFamily.id)
        .where(CourseRawTypeSuggestion.id == suggestion_id, CourseWorkItemLabelFamily.user_id == user_id)
        .limit(1)
    )


def decide_raw_type_suggestion(
    db: Session,
    *,
    user_id: int,
    suggestion: CourseRawTypeSuggestion,
    decision: str,
    note: str | None,
) -> CourseRawTypeSuggestion:
    normalized = decision.strip().lower()
    if normalized not in {"approve", "reject", "dismiss"}:
        raise CourseRawTypeValidationError("decision must be approve, reject, or dismiss")
    source_family = suggestion.source_raw_type.family
    if source_family is None or source_family.user_id != user_id:
        raise CourseRawTypeValidationError("raw type suggestion does not belong to user")
    if normalized == "approve":
        if suggestion.suggested_raw_type is None:
            raise CourseRawTypeValidationError("approve requires a suggested raw type target")
        move_course_raw_type_to_family(
            db,
            raw_type=suggestion.source_raw_type,
            family=suggestion.suggested_raw_type.family,
            commit=False,
        )
        suggestion.status = CourseRawTypeSuggestionStatus.APPROVED
    elif normalized == "reject":
        suggestion.status = CourseRawTypeSuggestionStatus.REJECTED
    else:
        suggestion.status = CourseRawTypeSuggestionStatus.DISMISSED
    suggestion.review_note = note[:512] if isinstance(note, str) and note.strip() else None
    suggestion.reviewed_at = datetime.now(timezone.utc)
    db.flush()
    return suggestion


def _coalesce_course_identity(
    *,
    course_key: str | None = None,
    course_dept: str | None = None,
    course_number: int | None = None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
) -> dict[str, object]:
    if course_key and (course_dept is None or course_number is None):
        parsed = parse_course_display(course_key)
        return {
            "course_dept": parsed["course_dept"] if isinstance(parsed["course_dept"], str) else None,
            "course_number": parsed["course_number"] if isinstance(parsed["course_number"], int) else None,
            "course_suffix": parsed["course_suffix"] if isinstance(parsed["course_suffix"], str) else None,
            "course_quarter": parsed["course_quarter"] if isinstance(parsed["course_quarter"], str) else None,
            "course_year2": parsed["course_year2"] if isinstance(parsed["course_year2"], int) else None,
        }
    return {
        "course_dept": course_dept,
        "course_number": course_number,
        "course_suffix": course_suffix,
        "course_quarter": course_quarter,
        "course_year2": course_year2,
    }
