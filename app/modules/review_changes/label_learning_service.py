from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import Change, ReviewStatus, SourceEventObservation
from app.db.models.shared import User
from app.modules.common.course_identity import course_display_name, course_identity_matches
from app.modules.core_ingest.course_work_item_family_rebuild import rebuild_user_work_item_state
from app.modules.review_changes.change_decision_service import ReviewChangeNotFoundError, decide_review_change
from app.modules.users.course_work_item_families_service import (
    CourseWorkItemFamilyValidationError,
    add_raw_type_to_course_work_item_family,
    create_course_work_item_family,
    get_course_work_item_family,
    list_course_work_item_families,
    resolve_course_work_item_family,
)


class LabelLearningValidationError(RuntimeError):
    pass


class LabelLearningNotFoundError(RuntimeError):
    pass


def preview_label_learning(
    db: Session,
    *,
    user_id: int,
    change_id: int,
) -> dict:
    change = _load_change(db, user_id=user_id, change_id=change_id)
    context = _load_learning_context(db=db, user_id=user_id, change=change)
    families = list_course_work_item_families(
        db,
        user_id=user_id,
        course_dept=context["course_dept"],
        course_number=context["course_number"],
        course_suffix=context["course_suffix"],
        course_quarter=context["course_quarter"],
        course_year2=context["course_year2"],
    )
    return {
        "change_id": change.id,
        "course_display": context["course_display"],
        "course_dept": context["course_dept"],
        "course_number": context["course_number"],
        "course_suffix": context["course_suffix"],
        "course_quarter": context["course_quarter"],
        "course_year2": context["course_year2"],
        "raw_label": context["raw_label"],
        "ordinal": context["ordinal"],
        "status": context["status"],
        "resolved_family_id": context["resolved_family_id"],
        "resolved_canonical_label": context["resolved_canonical_label"],
        "families": [
            {
                "id": row.id,
                "course_display": course_display_name(
                    course_dept=row.course_dept,
                    course_number=row.course_number,
                    course_suffix=row.course_suffix,
                    course_quarter=row.course_quarter,
                    course_year2=row.course_year2,
                )
                or "Unknown",
                "course_dept": row.course_dept,
                "course_number": row.course_number,
                "course_suffix": row.course_suffix,
                "course_quarter": row.course_quarter,
                "course_year2": row.course_year2,
                "canonical_label": row.canonical_label,
                "raw_types": [
                    item.raw_type
                    for item in (row.raw_types if isinstance(row.raw_types, list) else [])
                    if isinstance(getattr(item, "raw_type", None), str)
                ],
            }
            for row in families
        ],
    }


def apply_label_learning(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    mode: str,
    family_id: int | None,
    canonical_label: str | None,
) -> dict:
    change = _load_change(db, user_id=user_id, change_id=change_id)
    context = _load_learning_context(db=db, user_id=user_id, change=change)
    raw_label = context["raw_label"]
    if context["course_dept"] is None or context["course_number"] is None or not raw_label:
        raise LabelLearningValidationError("label learning requires current course identity and raw_label")

    target_family_id: int | None = None
    target_canonical_label: str | None = None
    if mode == "add_alias":
        if family_id is None:
            raise LabelLearningValidationError("family_id is required for add_alias")
        family = get_course_work_item_family(db, user_id=user_id, family_id=family_id)
        if family is None:
            raise LabelLearningNotFoundError("course work item family not found")
        if not course_identity_matches(
            {
                "course_dept": family.course_dept,
                "course_number": family.course_number,
                "course_suffix": family.course_suffix,
                "course_quarter": family.course_quarter,
                "course_year2": family.course_year2,
            },
            context,
        ):
            raise LabelLearningValidationError("family must belong to the same course")
        family = add_raw_type_to_course_work_item_family(db, family=family, raw_type=raw_label)
        target_family_id = family.id
        target_canonical_label = family.canonical_label
    elif mode == "create_family":
        label = (canonical_label or raw_label).strip()
        if not label:
            raise LabelLearningValidationError("canonical_label must not be blank")
        family = create_course_work_item_family(
            db,
            user_id=user_id,
            course_dept=context["course_dept"],
            course_number=context["course_number"],
            course_suffix=context["course_suffix"],
            course_quarter=context["course_quarter"],
            course_year2=context["course_year2"],
            canonical_label=label,
            raw_types=[raw_label] if label.strip().lower() != raw_label.strip().lower() else [],
        )
        target_family_id = family.id
        target_canonical_label = family.canonical_label
    else:
        raise LabelLearningValidationError("mode must be one of: add_alias, create_family")

    user = db.get(User, user_id)
    if user is None:
        raise LabelLearningNotFoundError("user not found")
    rebuild_user_work_item_state(
        db,
        user=user,
        course_dept=context["course_dept"],
        course_number=context["course_number"],
        course_suffix=context["course_suffix"],
        course_quarter=context["course_quarter"],
        course_year2=context["course_year2"],
    )

    approved_change_id = _approve_rebuilt_pending_change(
        db=db,
        user_id=user_id,
        source_id=context["source_id"],
        external_event_id=context["external_event_id"],
    )
    return {
        "applied": True,
        "course_display": context["course_display"],
        "course_dept": context["course_dept"],
        "course_number": context["course_number"],
        "course_suffix": context["course_suffix"],
        "course_quarter": context["course_quarter"],
        "course_year2": context["course_year2"],
        "raw_label": raw_label,
        "family_id": target_family_id,
        "canonical_label": target_canonical_label,
        "approved_change_id": approved_change_id,
    }


def _approve_rebuilt_pending_change(*, db: Session, user_id: int, source_id: int | None, external_event_id: str | None) -> int | None:
    if source_id is None or not external_event_id:
        return None
    rows = db.scalars(
        select(Change)
        .where(Change.user_id == user_id, Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.desc())
    ).all()
    for row in rows:
        sources = [
            {
                "source_id": source_ref.source_id,
                "external_event_id": source_ref.external_event_id,
            }
            for source_ref in row.source_refs
        ]
        for source in sources:
            if not isinstance(source, dict):
                continue
            if source.get("source_id") == source_id and source.get("external_event_id") == external_event_id:
                approved_row, _ = decide_review_change(db, user_id=user_id, change_id=row.id, decision="approve", note="learned_label_auto_approved")
                return int(approved_row.id)
    return None


def _load_change(db: Session, *, user_id: int, change_id: int) -> Change:
    row = db.scalar(
        select(Change).where(Change.id == change_id, Change.user_id == user_id).limit(1)
    )
    if row is None:
        raise ReviewChangeNotFoundError("Review change not found")
    return row


def _load_learning_context(*, db: Session, user_id: int, change: Change) -> dict:
    sources = [
        {
            "source_id": source_ref.source_id,
            "external_event_id": source_ref.external_event_id,
        }
        for source_ref in change.source_refs
    ]
    primary = next((row for row in sources if isinstance(row, dict) and isinstance(row.get("source_id"), int)), None)
    if primary is None:
        raise LabelLearningValidationError("label learning requires proposal source metadata")
    source_id = int(primary["source_id"])
    external_event_id = primary.get("external_event_id") if isinstance(primary.get("external_event_id"), str) else None
    observation = None
    if external_event_id:
        observation = db.scalar(
            select(SourceEventObservation)
            .where(
                SourceEventObservation.user_id == user_id,
                SourceEventObservation.source_id == source_id,
                SourceEventObservation.external_event_id == external_event_id,
            )
            .order_by(SourceEventObservation.observed_at.desc())
            .limit(1)
        )
    if observation is None:
        raise LabelLearningNotFoundError("supporting observation not found")
    payload = observation.event_payload if isinstance(observation.event_payload, dict) else {}
    enrichment = payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else {}
    course_parse = enrichment.get("course_parse") if isinstance(enrichment.get("course_parse"), dict) else {}
    semantic_event = payload.get("semantic_event") if isinstance(payload.get("semantic_event"), dict) else {}
    semantic_draft = payload.get("semantic_event_draft") if isinstance(payload.get("semantic_event_draft"), dict) else {}
    semantic_like = semantic_event or semantic_draft
    course_display = course_display_name(semantic_event=semantic_like) or course_display_name(course_parse=course_parse)
    course_dept = (
        semantic_like.get("course_dept") if isinstance(semantic_like.get("course_dept"), str) else course_parse.get("dept") if isinstance(course_parse.get("dept"), str) else None
    )
    course_number = (
        semantic_like.get("course_number") if isinstance(semantic_like.get("course_number"), int) else course_parse.get("number") if isinstance(course_parse.get("number"), int) else None
    )
    course_suffix = (
        semantic_like.get("course_suffix") if isinstance(semantic_like.get("course_suffix"), str) else course_parse.get("suffix") if isinstance(course_parse.get("suffix"), str) else None
    )
    course_quarter = (
        semantic_like.get("course_quarter") if isinstance(semantic_like.get("course_quarter"), str) else course_parse.get("quarter") if isinstance(course_parse.get("quarter"), str) else None
    )
    course_year2 = (
        semantic_like.get("course_year2") if isinstance(semantic_like.get("course_year2"), int) else course_parse.get("year2") if isinstance(course_parse.get("year2"), int) else None
    )
    raw_label = semantic_like.get("raw_type") if isinstance(semantic_like.get("raw_type"), str) else None
    ordinal = semantic_like.get("ordinal") if isinstance(semantic_like.get("ordinal"), int) else None
    resolution = resolve_course_work_item_family(
        db,
        user_id=user_id,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
        raw_label=raw_label,
    )
    return {
        "course_display": course_display,
        "course_dept": course_dept,
        "course_number": course_number,
        "course_suffix": course_suffix,
        "course_quarter": course_quarter,
        "course_year2": course_year2,
        "raw_label": raw_label,
        "ordinal": ordinal,
        "status": resolution.get("status") or "unresolved",
        "resolved_family_id": resolution.get("family_id"),
        "resolved_canonical_label": resolution.get("canonical_label"),
        "source_id": source_id,
        "external_event_id": external_event_id,
    }


__all__ = [
    "LabelLearningNotFoundError",
    "LabelLearningValidationError",
    "apply_label_learning",
    "preview_label_learning",
]
