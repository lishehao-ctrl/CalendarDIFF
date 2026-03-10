from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import Change, Input, ReviewStatus, SourceEventObservation
from app.modules.core_ingest.entity_profile import course_display_name
from app.modules.core_ingest.course_work_item_family_rebuild import rebuild_user_work_item_state
from app.modules.core_ingest.course_work_item_family_resolution import normalize_work_item_parse
from app.modules.review_changes.change_decision_service import ReviewChangeNotFoundError, decide_review_change
from app.modules.users.course_work_item_families_service import (
    CourseWorkItemFamilyValidationError,
    add_alias_to_course_work_item_family,
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
    families = list_course_work_item_families(db, user_id=user_id, course_key=context["course_key"])
    return {
        "change_id": change.id,
        "course_key": context["course_key"],
        "raw_label": context["raw_label"],
        "ordinal": context["ordinal"],
        "status": context["status"],
        "resolved_family_id": context["resolved_family_id"],
        "resolved_canonical_label": context["resolved_canonical_label"],
        "families": [
            {
                "id": row.id,
                "course_key": row.course_key,
                "canonical_label": row.canonical_label,
                "aliases": row.aliases_json if isinstance(row.aliases_json, list) else [],
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
    course_key = context["course_key"]
    if not course_key or not raw_label:
        raise LabelLearningValidationError("label learning requires current course_key and raw_label")

    target_family_id: int | None = None
    target_canonical_label: str | None = None
    if mode == "add_alias":
        if family_id is None:
            raise LabelLearningValidationError("family_id is required for add_alias")
        family = get_course_work_item_family(db, user_id=user_id, family_id=family_id)
        if family is None:
            raise LabelLearningNotFoundError("course work item family not found")
        if family.course_key.strip() != course_key:
            raise LabelLearningValidationError("family must belong to the same course")
        family = add_alias_to_course_work_item_family(db, family=family, alias=raw_label)
        target_family_id = family.id
        target_canonical_label = family.canonical_label
    elif mode == "create_family":
        label = (canonical_label or raw_label).strip()
        if not label:
            raise LabelLearningValidationError("canonical_label must not be blank")
        family = create_course_work_item_family(
            db,
            user_id=user_id,
            course_key=course_key,
            canonical_label=label,
            aliases=[raw_label] if label.strip().lower() != raw_label.strip().lower() else [],
        )
        target_family_id = family.id
        target_canonical_label = family.canonical_label
    else:
        raise LabelLearningValidationError("mode must be one of: add_alias, create_family")

    user = db.get(Input, change.input_id).user  # type: ignore[union-attr]
    if user is None:
        raise LabelLearningNotFoundError("user not found")
    rebuild_user_work_item_state(db, user=user, course_key=course_key)

    approved_change_id = _approve_rebuilt_pending_change(
        db=db,
        user_id=user_id,
        source_id=context["source_id"],
        external_event_id=context["external_event_id"],
    )
    return {
        "applied": True,
        "course_key": course_key,
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
        .join(Input, Input.id == Change.input_id)
        .where(Input.user_id == user_id, Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.desc())
    ).all()
    for row in rows:
        sources = row.proposal_sources_json if isinstance(row.proposal_sources_json, list) else []
        for source in sources:
            if not isinstance(source, dict):
                continue
            if source.get("source_id") == source_id and source.get("external_event_id") == external_event_id:
                approved_row, _ = decide_review_change(db, user_id=user_id, change_id=row.id, decision="approve", note="learned_label_auto_approved")
                return int(approved_row.id)
    return None


def _load_change(db: Session, *, user_id: int, change_id: int) -> Change:
    row = db.scalar(
        select(Change)
        .join(Input, Input.id == Change.input_id)
        .where(Change.id == change_id, Input.user_id == user_id)
        .limit(1)
    )
    if row is None:
        raise ReviewChangeNotFoundError("Review change not found")
    return row


def _load_learning_context(*, db: Session, user_id: int, change: Change) -> dict:
    sources = change.proposal_sources_json if isinstance(change.proposal_sources_json, list) else []
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
    work_item_parse = normalize_work_item_parse(enrichment.get("work_item_parse"))
    course_key = course_display_name(course_parse=course_parse)
    resolution = resolve_course_work_item_family(db, user_id=user_id, course_key=course_key, raw_label=work_item_parse.get("raw_label"))
    return {
        "course_key": course_key,
        "raw_label": work_item_parse.get("raw_label"),
        "ordinal": work_item_parse.get("ordinal"),
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
