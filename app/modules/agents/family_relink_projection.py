from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import Change, EventEntity, EventEntityLifecycle, ReviewStatus, SourceEventObservation
from app.db.models.shared import CourseRawTypeSuggestion, CourseRawTypeSuggestionStatus, CourseWorkItemLabelFamily, CourseWorkItemRawType
from app.modules.common.course_identity import course_display_name, normalize_label_token
from app.modules.families.family_service import get_course_work_item_family
from app.modules.families.raw_type_service import get_course_raw_type


class FamilyRelinkProjectionValidationError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def build_family_relink_projection(
    db: Session,
    *,
    user_id: int,
    raw_type_id: int,
    family_id: int,
) -> dict:
    raw_type = get_course_raw_type(db, user_id=user_id, raw_type_id=raw_type_id)
    if raw_type is None:
        raise FamilyRelinkProjectionValidationError(
            code="agents.context.raw_type_not_found",
            message="Observed label not found",
        )
    target_family = get_course_work_item_family(db, user_id=user_id, family_id=family_id)
    if target_family is None:
        raise FamilyRelinkProjectionValidationError(
            code="agents.context.family_not_found",
            message="Family not found",
        )
    current_family = raw_type.family
    if current_family is None:
        raise FamilyRelinkProjectionValidationError(
            code="agents.proposals.family.current_family_missing",
            message="Observed label must belong to a canonical family",
        )
    if int(current_family.id) == int(target_family.id):
        raise FamilyRelinkProjectionValidationError(
            code="agents.proposals.family.already_in_family",
            message="Observed label is already mapped to this canonical family",
        )
    if current_family.user_id != target_family.user_id or current_family.normalized_course_identity != target_family.normalized_course_identity:
        raise FamilyRelinkProjectionValidationError(
            code="agents.proposals.family.cross_course_not_allowed",
            message="Observed label can only move within the same course",
        )

    impacted_entity_uids = _load_impacted_entity_uids(
        db=db,
        user_id=user_id,
        raw_type=raw_type,
        current_family=current_family,
    )
    impacted_events = _load_impacted_events(
        db=db,
        user_id=user_id,
        impacted_entity_uids=impacted_entity_uids,
    )
    impacted_pending_changes = _load_impacted_pending_changes(
        db=db,
        user_id=user_id,
        impacted_entity_uids=impacted_entity_uids,
    )
    matching_suggestion_count = _count_matching_suggestions(
        db=db,
        raw_type=raw_type,
        target_family=target_family,
    )
    impacted_event_count = len(impacted_events)
    impacted_pending_change_count = len(impacted_pending_changes)
    risk_level = "low" if impacted_pending_change_count == 0 else "medium"
    risk_reason_code = (
        "agents.proposals.family_relink_commit.low_risk"
        if risk_level == "low"
        else "agents.proposals.family_relink_commit.pending_changes_present"
    )

    return {
        "raw_type": {
            "raw_type_id": raw_type.id,
            "raw_type": raw_type.raw_type,
            "normalized_raw_type": raw_type.normalized_raw_type,
        },
        "course": {
            "course_display": course_display_name(
                course_dept=current_family.course_dept,
                course_number=current_family.course_number,
                course_suffix=current_family.course_suffix,
                course_quarter=current_family.course_quarter,
                course_year2=current_family.course_year2,
            ),
            "normalized_course_identity": current_family.normalized_course_identity,
        },
        "current_family": _serialize_family_snapshot(current_family),
        "target_family": _serialize_family_snapshot(target_family),
        "impact": {
            "impacted_event_count": impacted_event_count,
            "impacted_pending_change_count": impacted_pending_change_count,
            "matching_suggestion_count": matching_suggestion_count,
            "active_event_samples": impacted_events[:3],
            "pending_change_samples": impacted_pending_changes[:3],
            "risk_level": risk_level,
            "risk_reason_code": risk_reason_code,
        },
    }


def _load_impacted_entity_uids(
    *,
    db: Session,
    user_id: int,
    raw_type: CourseWorkItemRawType,
    current_family: CourseWorkItemLabelFamily,
) -> set[str]:
    rows = list(
        db.scalars(
            select(SourceEventObservation)
            .where(
                SourceEventObservation.user_id == user_id,
                SourceEventObservation.is_active.is_(True),
            )
            .order_by(SourceEventObservation.observed_at.desc(), SourceEventObservation.id.desc())
        ).all()
    )
    impacted: set[str] = set()
    expected_raw_type = raw_type.normalized_raw_type
    for row in rows:
        payload = row.event_payload if isinstance(row.event_payload, dict) else {}
        semantic_event = payload.get("semantic_event") if isinstance(payload.get("semantic_event"), dict) else {}
        if int(semantic_event.get("family_id") or 0) != int(current_family.id):
            continue
        if normalize_label_token(semantic_event.get("raw_type")) != expected_raw_type:
            continue
        entity_uid = str(row.entity_uid or "").strip()
        if entity_uid:
            impacted.add(entity_uid)
    return impacted


def _load_impacted_events(
    *,
    db: Session,
    user_id: int,
    impacted_entity_uids: set[str],
) -> list[dict]:
    if not impacted_entity_uids:
        return []
    rows = list(
        db.scalars(
            select(EventEntity)
            .where(
                EventEntity.user_id == user_id,
                EventEntity.lifecycle == EventEntityLifecycle.ACTIVE,
                EventEntity.entity_uid.in_(sorted(impacted_entity_uids)),
            )
            .order_by(EventEntity.updated_at.desc(), EventEntity.id.desc())
        ).all()
    )
    return [
        {
            "entity_uid": row.entity_uid,
            "event_name": row.event_name,
            "ordinal": row.ordinal,
            "raw_type": row.raw_type,
        }
        for row in rows
    ]


def _load_impacted_pending_changes(
    *,
    db: Session,
    user_id: int,
    impacted_entity_uids: set[str],
) -> list[dict]:
    if not impacted_entity_uids:
        return []
    rows = list(
        db.scalars(
            select(Change)
            .where(
                Change.user_id == user_id,
                Change.review_status == ReviewStatus.PENDING,
                Change.entity_uid.in_(sorted(impacted_entity_uids)),
            )
            .order_by(Change.detected_at.desc(), Change.id.desc())
        ).all()
    )
    return [
        {
            "change_id": row.id,
            "change_type": row.change_type.value,
            "review_bucket": row.review_bucket.value,
            "entity_uid": row.entity_uid,
        }
        for row in rows
    ]


def _count_matching_suggestions(
    *,
    db: Session,
    raw_type: CourseWorkItemRawType,
    target_family: CourseWorkItemLabelFamily,
) -> int:
    rows = list(
        db.scalars(
            select(CourseRawTypeSuggestion)
            .where(
                CourseRawTypeSuggestion.source_raw_type_id == raw_type.id,
                CourseRawTypeSuggestion.status == CourseRawTypeSuggestionStatus.PENDING,
            )
            .order_by(CourseRawTypeSuggestion.created_at.desc(), CourseRawTypeSuggestion.id.desc())
        ).all()
    )
    return sum(
        1
        for row in rows
        if row.suggested_raw_type is not None and int(row.suggested_raw_type.family_id or 0) == int(target_family.id)
    )


def _serialize_family_snapshot(row: CourseWorkItemLabelFamily) -> dict:
    return {
        "family_id": row.id,
        "canonical_label": row.canonical_label,
        "course_display": course_display_name(
            course_dept=row.course_dept,
            course_number=row.course_number,
            course_suffix=row.course_suffix,
            course_quarter=row.course_quarter,
            course_year2=row.course_year2,
        ),
        "normalized_course_identity": row.normalized_course_identity,
    }


__all__ = [
    "FamilyRelinkProjectionValidationError",
    "build_family_relink_projection",
]
