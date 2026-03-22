from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import Change, ChangeOrigin, ChangeType, EventEntity, EventEntityLifecycle, ReviewStatus
from app.modules.common.course_identity import course_display_name
from app.modules.common.event_display import user_facing_event_view
from app.modules.common.payload_schemas import ApprovedSemanticPayload
from app.modules.common.semantic_codec import approved_entity_to_semantic_payload, semantic_delta_seconds, semantic_payloads_equivalent
from app.modules.common.change_evidence import freeze_semantic_evidence
from app.modules.families.family_service import get_course_work_item_family, normalize_label_token
from app.modules.manual.schemas import ManualEventWriteRequest
from app.modules.changes.approved_entity_state import apply_approved_entity_state
from app.modules.changes.canonical_edit_audit import emit_canonical_edit_audit_event, reject_conflicting_pending_changes


class ManualEventNotFoundError(RuntimeError):
    pass


class ManualEventValidationError(RuntimeError):
    pass


def list_manual_events(
    db: Session,
    *,
    user_id: int,
    include_removed: bool = False,
) -> list[dict]:
    stmt = (
        select(EventEntity)
        .where(
            EventEntity.user_id == user_id,
            EventEntity.event_name.is_not(None),
            EventEntity.due_date.is_not(None),
        )
        .order_by(
            EventEntity.course_dept.asc(),
            EventEntity.course_number.asc(),
            EventEntity.course_suffix.asc(),
            EventEntity.course_quarter.asc(),
            EventEntity.course_year2.asc(),
            EventEntity.family_id.asc(),
            EventEntity.due_date.asc(),
            EventEntity.due_time.asc(),
            EventEntity.event_name.asc(),
            EventEntity.entity_uid.asc(),
        )
    )
    if not include_removed:
        stmt = stmt.where(EventEntity.lifecycle == EventEntityLifecycle.ACTIVE)
    rows = list(db.scalars(stmt).all())
    return [_serialize_manual_event(db=db, row=row) for row in rows]


def create_manual_event(
    db: Session,
    *,
    user_id: int,
    payload: ManualEventWriteRequest,
) -> dict:
    family = get_course_work_item_family(db, user_id=user_id, family_id=payload.family_id)
    if family is None:
        raise ManualEventNotFoundError("course work item family not found")

    entity_uid = f"manual-{uuid4().hex[:12]}"
    after_payload = _build_semantic_payload(entity_uid=entity_uid, payload=payload, family=family)
    now = datetime.now(timezone.utc)

    approved_entity = apply_approved_entity_state(
        db=db,
        user_id=user_id,
        entity_uid=entity_uid,
        change_type=ChangeType.CREATED,
        semantic_payload=after_payload,
    )
    if approved_entity is None:
        raise ManualEventValidationError("unable to create manual event")
    approved_entity.manual_support = True

    after_evidence = freeze_semantic_evidence(provider=None, semantic_payload=after_payload)
    reason_note = _reason_note(prefix="manual_create", reason=payload.reason)
    audit_change = Change(
        user_id=user_id,
        entity_uid=entity_uid,
        change_origin=ChangeOrigin.MANUAL_CANONICAL_EDIT,
        change_type=ChangeType.CREATED,
        detected_at=now,
        before_semantic_json=None,
        after_semantic_json=after_payload,
        delta_seconds=None,
        before_evidence_json=None,
        after_evidence_json=after_evidence.model_dump(mode="json") if after_evidence is not None else None,
        viewed_at=None,
        viewed_note=None,
        review_status=ReviewStatus.APPROVED,
        reviewed_at=now,
        review_note=reason_note,
        reviewed_by_user_id=user_id,
    )
    db.add(audit_change)
    db.flush()
    change_id = int(audit_change.id)
    emit_canonical_edit_audit_event(
        db=db,
        change_id=change_id,
        entity_uid=entity_uid,
        reviewed_by_user_id=user_id,
        reviewed_at=now,
        rejected_pending_change_ids=[],
    )
    db.commit()
    db.refresh(approved_entity)
    return {
        "applied": True,
        "idempotent": False,
        "change_id": change_id,
        "entity_uid": entity_uid,
        "lifecycle": approved_entity.lifecycle.value,
        "event": _serialize_manual_event(db=db, row=approved_entity),
    }


def update_manual_event(
    db: Session,
    *,
    user_id: int,
    entity_uid: str,
    payload: ManualEventWriteRequest,
) -> dict:
    normalized_entity_uid = _normalize_entity_uid(entity_uid)
    row = db.scalar(
        select(EventEntity)
        .where(EventEntity.user_id == user_id, EventEntity.entity_uid == normalized_entity_uid)
        .with_for_update()
        .limit(1)
    )
    if row is None:
        raise ManualEventNotFoundError("manual event not found")
    if row.lifecycle != EventEntityLifecycle.ACTIVE:
        raise ManualEventValidationError("removed events cannot be edited")

    family = get_course_work_item_family(db, user_id=user_id, family_id=payload.family_id)
    if family is None:
        raise ManualEventNotFoundError("course work item family not found")

    before_payload = approved_entity_to_semantic_payload(
        row,
        family_name_override=_resolve_family_name(db=db, row=row),
    )
    after_payload = _build_semantic_payload(entity_uid=normalized_entity_uid, payload=payload, family=family)
    idempotent = semantic_payloads_equivalent(before_payload, after_payload)
    if idempotent:
        if not row.manual_support:
            row.manual_support = True
            db.commit()
            db.refresh(row)
        return {
            "applied": True,
            "idempotent": True,
            "change_id": None,
            "entity_uid": normalized_entity_uid,
            "lifecycle": row.lifecycle.value,
            "event": _serialize_manual_event(db=db, row=row),
        }

    now = datetime.now(timezone.utc)
    approved_entity = apply_approved_entity_state(
        db=db,
        user_id=user_id,
        entity_uid=normalized_entity_uid,
        change_type=ChangeType.DUE_CHANGED,
        semantic_payload=after_payload,
    )
    if approved_entity is None:
        raise ManualEventValidationError("unable to update manual event")
    approved_entity.manual_support = True

    before_evidence = freeze_semantic_evidence(provider=None, semantic_payload=before_payload)
    after_evidence = freeze_semantic_evidence(provider=None, semantic_payload=after_payload)
    reason_note = _reason_note(prefix="manual_edit", reason=payload.reason)
    audit_change = Change(
        user_id=user_id,
        entity_uid=normalized_entity_uid,
        change_origin=ChangeOrigin.MANUAL_CANONICAL_EDIT,
        change_type=ChangeType.DUE_CHANGED,
        detected_at=now,
        before_semantic_json=before_payload,
        after_semantic_json=after_payload,
        delta_seconds=semantic_delta_seconds(before_payload=before_payload, after_payload=after_payload),
        before_evidence_json=before_evidence.model_dump(mode="json") if before_evidence is not None else None,
        after_evidence_json=after_evidence.model_dump(mode="json") if after_evidence is not None else None,
        viewed_at=None,
        viewed_note=None,
        review_status=ReviewStatus.APPROVED,
        reviewed_at=now,
        review_note=reason_note,
        reviewed_by_user_id=user_id,
    )
    db.add(audit_change)
    db.flush()
    change_id = int(audit_change.id)
    rejected_pending_change_ids = reject_conflicting_pending_changes(
        db=db,
        user_id=user_id,
        entity_uid=normalized_entity_uid,
        reviewed_at=now,
        reviewed_by_user_id=user_id,
        canonical_edit_change_id=change_id,
    )
    emit_canonical_edit_audit_event(
        db=db,
        change_id=change_id,
        entity_uid=normalized_entity_uid,
        reviewed_by_user_id=user_id,
        reviewed_at=now,
        rejected_pending_change_ids=rejected_pending_change_ids,
    )
    db.commit()
    db.refresh(approved_entity)
    return {
        "applied": True,
        "idempotent": False,
        "change_id": change_id,
        "entity_uid": normalized_entity_uid,
        "lifecycle": approved_entity.lifecycle.value,
        "event": _serialize_manual_event(db=db, row=approved_entity),
    }


def delete_manual_event(
    db: Session,
    *,
    user_id: int,
    entity_uid: str,
    reason: str | None = None,
) -> dict:
    normalized_entity_uid = _normalize_entity_uid(entity_uid)
    row = db.scalar(
        select(EventEntity)
        .where(EventEntity.user_id == user_id, EventEntity.entity_uid == normalized_entity_uid)
        .with_for_update()
        .limit(1)
    )
    if row is None:
        raise ManualEventNotFoundError("manual event not found")
    if row.lifecycle == EventEntityLifecycle.REMOVED:
        if not row.manual_support:
            row.manual_support = True
            db.commit()
            db.refresh(row)
        return {
            "applied": True,
            "idempotent": True,
            "change_id": None,
            "entity_uid": normalized_entity_uid,
            "lifecycle": row.lifecycle.value,
            "event": None,
        }

    before_payload = approved_entity_to_semantic_payload(
        row,
        family_name_override=_resolve_family_name(db=db, row=row),
    )
    now = datetime.now(timezone.utc)
    removed_entity = apply_approved_entity_state(
        db=db,
        user_id=user_id,
        entity_uid=normalized_entity_uid,
        change_type=ChangeType.REMOVED,
        semantic_payload=None,
    )
    if removed_entity is None:
        raise ManualEventValidationError("unable to delete manual event")
    removed_entity.manual_support = True

    before_evidence = freeze_semantic_evidence(provider=None, semantic_payload=before_payload)
    reason_note = _reason_note(prefix="manual_delete", reason=reason)
    audit_change = Change(
        user_id=user_id,
        entity_uid=normalized_entity_uid,
        change_origin=ChangeOrigin.MANUAL_CANONICAL_EDIT,
        change_type=ChangeType.REMOVED,
        detected_at=now,
        before_semantic_json=before_payload,
        after_semantic_json=None,
        delta_seconds=None,
        before_evidence_json=before_evidence.model_dump(mode="json") if before_evidence is not None else None,
        after_evidence_json=None,
        viewed_at=None,
        viewed_note=None,
        review_status=ReviewStatus.APPROVED,
        reviewed_at=now,
        review_note=reason_note,
        reviewed_by_user_id=user_id,
    )
    db.add(audit_change)
    db.flush()
    change_id = int(audit_change.id)
    rejected_pending_change_ids = reject_conflicting_pending_changes(
        db=db,
        user_id=user_id,
        entity_uid=normalized_entity_uid,
        reviewed_at=now,
        reviewed_by_user_id=user_id,
        canonical_edit_change_id=change_id,
    )
    emit_canonical_edit_audit_event(
        db=db,
        change_id=change_id,
        entity_uid=normalized_entity_uid,
        reviewed_by_user_id=user_id,
        reviewed_at=now,
        rejected_pending_change_ids=rejected_pending_change_ids,
    )
    db.commit()
    db.refresh(removed_entity)
    return {
        "applied": True,
        "idempotent": False,
        "change_id": change_id,
        "entity_uid": normalized_entity_uid,
        "lifecycle": removed_entity.lifecycle.value,
        "event": None,
    }


def _build_semantic_payload(
    *,
    entity_uid: str,
    payload: ManualEventWriteRequest,
    family,
) -> dict:
    raw_type = _normalize_raw_type(payload.raw_type) or family.canonical_label
    try:
        model = ApprovedSemanticPayload.model_validate(
            {
                "uid": entity_uid,
                "family_id": family.id,
                "family_name": family.canonical_label,
                "course_dept": family.course_dept,
                "course_number": family.course_number,
                "course_suffix": family.course_suffix,
                "course_quarter": family.course_quarter,
                "course_year2": family.course_year2,
                "raw_type": raw_type,
                "event_name": payload.event_name,
                "ordinal": payload.ordinal,
                "due_date": payload.due_date,
                "due_time": payload.due_time,
                "time_precision": payload.time_precision,
            }
        )
    except Exception as exc:
        raise ManualEventValidationError("manual event payload is invalid") from exc
    return model.to_json_dict()


def _normalize_entity_uid(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ManualEventValidationError("entity_uid must not be blank")
    return cleaned


def _normalize_raw_type(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    normalized = normalize_label_token(cleaned)
    return cleaned[:128] if normalized else None


def _reason_note(*, prefix: str, reason: str | None) -> str:
    cleaned = (reason or "").strip()
    if not cleaned:
        return prefix
    return f"{prefix}:{cleaned[:512]}"


def _resolve_family_name(*, db: Session, row: EventEntity) -> str:
    if isinstance(row.family_id, int) and row.family_id > 0:
        family = get_course_work_item_family(db, user_id=row.user_id, family_id=row.family_id)
        if family is not None and isinstance(family.canonical_label, str) and family.canonical_label.strip():
            return family.canonical_label.strip()
    if isinstance(row.raw_type, str) and row.raw_type.strip():
        return row.raw_type.strip()
    return "Unfiled"


def _serialize_manual_event(*, db: Session, row: EventEntity) -> dict:
    family_name = _resolve_family_name(db=db, row=row)
    payload = approved_entity_to_semantic_payload(row, family_name_override=family_name)
    event_view = user_facing_event_view(payload, strict=False, family_name_override=family_name)
    course_display = course_display_name(semantic_event=payload) or "Unknown course"
    return {
        "entity_uid": row.entity_uid,
        "lifecycle": row.lifecycle.value,
        "manual_support": bool(row.manual_support),
        "family_id": row.family_id,
        "family_name": family_name,
        "course_display": course_display,
        "course_dept": row.course_dept,
        "course_number": row.course_number,
        "course_suffix": row.course_suffix,
        "course_quarter": row.course_quarter,
        "course_year2": row.course_year2,
        "raw_type": row.raw_type,
        "event_name": row.event_name,
        "ordinal": row.ordinal,
        "due_date": payload.get("due_date"),
        "due_time": payload.get("due_time"),
        "time_precision": payload.get("time_precision") or "datetime",
        "event": event_view,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


__all__ = [
    "ManualEventNotFoundError",
    "ManualEventValidationError",
    "create_manual_event",
    "delete_manual_event",
    "list_manual_events",
    "update_manual_event",
]
