from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import Change, ChangeType, ReviewStatus
from app.modules.common.event_display import user_facing_event_view
from app.modules.common.family_labels import load_latest_family_labels, require_latest_family_label
from app.modules.core_ingest.review_evidence import freeze_semantic_evidence
from app.modules.common.semantic_codec import parse_semantic_payload, semantic_delta_seconds, semantic_payloads_equivalent
from app.modules.review_changes.canonical_edit_builder import build_candidate_after, edit_payload_from_event_json
from app.modules.review_changes.canonical_edit_errors import CanonicalEditNotFoundError, CanonicalEditValidationError
from app.modules.review_changes.canonical_edit_apply_txn import execute_canonical_edit_apply_txn
from app.modules.review_changes.canonical_edit_preview_flow import build_canonical_edit_preview
from app.modules.review_changes.canonical_edit_target import load_user_or_raise


class ReviewEditNotFoundError(RuntimeError):
    pass


class ReviewEditValidationError(RuntimeError):
    pass


class ReviewEditInvalidStateError(RuntimeError):
    pass


def preview_review_edit(
    db: Session,
    *,
    user_id: int,
    mode: str,
    change_id: int | None,
    entity_uid: str | None,
    patch: dict,
    reason: str | None,
) -> dict:
    if mode == "proposal":
        return _preview_proposal_edit(
            db=db,
            user_id=user_id,
            change_id=change_id,
            patch=patch,
        )
    if mode == "canonical":
        try:
            payload = build_canonical_edit_preview(
                db=db,
                user_id=user_id,
                change_id=change_id,
                entity_uid=entity_uid,
                patch=patch,
                reason=reason,
            )
        except CanonicalEditNotFoundError as exc:
            raise ReviewEditNotFoundError(str(exc)) from exc
        except CanonicalEditValidationError as exc:
            raise ReviewEditValidationError(str(exc)) from exc
        latest_family_labels = _load_latest_family_labels_for_payloads(db=db, user_id=user_id, payloads=[payload["base"], payload["candidate_after"]])
        base_family_name = _resolve_family_name_override(payload=payload["base"], latest_family_labels=latest_family_labels)
        candidate_family_name = _resolve_family_name_override(payload=payload["candidate_after"], latest_family_labels=latest_family_labels)
        return {
            "mode": "canonical",
            "entity_uid": payload["entity_uid"],
            "change_id": change_id,
            "proposal_change_type": None,
            "base": user_facing_event_view(payload["base"], strict=True, family_name_override=base_family_name),
            "candidate_after": user_facing_event_view(
                payload["candidate_after"],
                strict=True,
                family_name_override=candidate_family_name,
            ),
            "delta_seconds": payload["delta_seconds"],
            "will_reject_pending_change_ids": payload["will_reject_pending_change_ids"],
            "idempotent": payload["idempotent"],
        }
    raise ReviewEditValidationError("mode must be one of: proposal, canonical")


def load_review_edit_context(
    db: Session,
    *,
    user_id: int,
    change_id: int,
) -> dict:
    row = db.scalar(
        select(Change).where(Change.id == change_id, Change.user_id == user_id).limit(1)
    )
    if row is None:
        raise ReviewEditNotFoundError("target change not found")
    semantic_payload = (
        row.after_semantic_json
        if isinstance(row.after_semantic_json, dict)
        else row.before_semantic_json
        if isinstance(row.before_semantic_json, dict)
        else None
    )
    if semantic_payload is None:
        raise ReviewEditValidationError("change has no editable semantic payload")
    parsed = parse_semantic_payload(row.entity_uid, semantic_payload)
    if parsed is None:
        raise ReviewEditValidationError("change payload is invalid")
    latest_family_labels = load_latest_family_labels(db, user_id=user_id, family_ids=[parsed.family_id])
    current_family_name = require_latest_family_label(
        family_id=parsed.family_id,
        latest_family_labels=latest_family_labels,
        context=f"review_changes.edit_context change_id={row.id}",
    )
    return {
        "change_id": row.id,
        "entity_uid": row.entity_uid,
        "editable_event": {
            "uid": row.entity_uid,
            "family_id": parsed.family_id,
            "family_name": current_family_name,
            "course_dept": parsed.course_dept,
            "course_number": parsed.course_number,
            "course_suffix": parsed.course_suffix,
            "course_quarter": parsed.course_quarter,
            "course_year2": parsed.course_year2,
            "raw_type": parsed.raw_type,
            "event_name": parsed.event_name,
            "ordinal": parsed.ordinal,
            "due_date": parsed.due_date.isoformat() if parsed.due_date is not None else None,
            "due_time": parsed.due_time.isoformat() if parsed.due_time is not None else None,
            "time_precision": parsed.time_precision or "datetime",
        },
    }


def apply_review_edit(
    db: Session,
    *,
    user_id: int,
    mode: str,
    change_id: int | None,
    entity_uid: str | None,
    patch: dict,
    reason: str | None,
) -> dict:
    if mode == "proposal":
        return _apply_proposal_edit(
            db=db,
            user_id=user_id,
            change_id=change_id,
            patch=patch,
        )
    if mode == "canonical":
        try:
            payload = execute_canonical_edit_apply_txn(
                db=db,
                user_id=user_id,
                change_id=change_id,
                entity_uid=entity_uid,
                patch=patch,
                reason=reason,
            )
        except CanonicalEditNotFoundError as exc:
            raise ReviewEditNotFoundError(str(exc)) from exc
        except CanonicalEditValidationError as exc:
            raise ReviewEditValidationError(str(exc)) from exc
        latest_family_labels = _load_latest_family_labels_for_payloads(db=db, user_id=user_id, payloads=[payload["event"]])
        event_family_name = _resolve_family_name_override(payload=payload["event"], latest_family_labels=latest_family_labels)
        return {
            "mode": "canonical",
            "applied": payload["applied"],
            "idempotent": payload["idempotent"],
            "entity_uid": payload["entity_uid"],
            "edited_change_id": None,
            "canonical_edit_change_id": payload["canonical_edit_change_id"],
            "rejected_pending_change_ids": payload["rejected_pending_change_ids"],
            "event": user_facing_event_view(payload["event"], strict=True, family_name_override=event_family_name),
        }
    raise ReviewEditValidationError("mode must be one of: proposal, canonical")


def _preview_proposal_edit(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
    patch: dict,
) -> dict:
    row = _load_pending_proposal_change(db=db, user_id=user_id, change_id=change_id, for_update=False)
    current_payload = _current_proposal_payload(row)
    candidate_after = build_candidate_after(
        entity_uid=row.entity_uid,
        base_payload=current_payload,
        patch=patch,
    )
    latest_family_labels = _load_latest_family_labels_for_payloads(db=db, user_id=user_id, payloads=[current_payload, candidate_after])
    base_family_name = _resolve_family_name_override(payload=current_payload, latest_family_labels=latest_family_labels)
    candidate_family_name = _resolve_family_name_override(payload=candidate_after, latest_family_labels=latest_family_labels)
    return {
        "mode": "proposal",
        "entity_uid": row.entity_uid,
        "change_id": row.id,
        "proposal_change_type": row.change_type.value,
        "base": user_facing_event_view(
            edit_payload_from_event_json(current_payload),
            strict=True,
            family_name_override=base_family_name,
        ),
        "candidate_after": user_facing_event_view(
            edit_payload_from_event_json(candidate_after),
            strict=True,
            family_name_override=candidate_family_name,
        ),
        "delta_seconds": _proposal_delta_seconds(row=row, candidate_after_payload=candidate_after),
        "will_reject_pending_change_ids": [],
        "idempotent": semantic_payloads_equivalent(current_payload, candidate_after),
    }


def _apply_proposal_edit(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
    patch: dict,
) -> dict:
    row = _load_pending_proposal_change(db=db, user_id=user_id, change_id=change_id, for_update=True)
    current_payload = _current_proposal_payload(row)
    candidate_after = build_candidate_after(
        entity_uid=row.entity_uid,
        base_payload=current_payload,
        patch=patch,
    )
    idempotent = semantic_payloads_equivalent(current_payload, candidate_after)
    if not idempotent:
        row.after_semantic_json = candidate_after
        row.delta_seconds = _proposal_delta_seconds(row=row, candidate_after_payload=candidate_after)
    if row.after_evidence_json is None or not idempotent:
        evidence = freeze_semantic_evidence(provider=None, semantic_payload=candidate_after)
        row.after_evidence_json = evidence.model_dump(mode="json") if evidence is not None else None
    db.commit()
    db.refresh(row)
    latest_family_labels = _load_latest_family_labels_for_payloads(db=db, user_id=user_id, payloads=[candidate_after])
    event_family_name = _resolve_family_name_override(payload=candidate_after, latest_family_labels=latest_family_labels)
    return {
        "mode": "proposal",
        "applied": True,
        "idempotent": idempotent,
        "entity_uid": row.entity_uid,
        "edited_change_id": row.id,
        "canonical_edit_change_id": None,
        "rejected_pending_change_ids": [],
        "event": user_facing_event_view(
            edit_payload_from_event_json(candidate_after),
            strict=True,
            family_name_override=event_family_name,
        ),
    }


def _load_pending_proposal_change(
    *,
    db: Session,
    user_id: int,
    change_id: int | None,
    for_update: bool,
) -> Change:
    if change_id is None:
        raise ReviewEditValidationError("proposal edits require target.change_id")
    stmt = select(Change).where(Change.id == change_id, Change.user_id == user_id).limit(1)
    if for_update:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        raise ReviewEditNotFoundError("target change not found")
    if row.review_status != ReviewStatus.PENDING:
        raise ReviewEditInvalidStateError("proposal edits require a pending change")
    if row.change_type not in {ChangeType.CREATED, ChangeType.DUE_CHANGED}:
        raise ReviewEditInvalidStateError("proposal edits only support created or due_changed changes")
    return row


def _current_proposal_payload(row: Change) -> dict:
    semantic_payload = row.after_semantic_json if isinstance(row.after_semantic_json, dict) else None
    if semantic_payload is None:
        raise ReviewEditValidationError("pending proposal has no editable semantic payload")
    parsed = parse_semantic_payload(row.entity_uid, semantic_payload)
    if parsed is None:
        raise ReviewEditValidationError("pending proposal semantic payload is invalid")
    return {
        "uid": row.entity_uid,
        "course_dept": parsed.course_dept,
        "course_number": parsed.course_number,
        "course_suffix": parsed.course_suffix,
        "course_quarter": parsed.course_quarter,
        "course_year2": parsed.course_year2,
        "family_id": parsed.family_id,
        "family_name": parsed.family_name,
        "raw_type": parsed.raw_type,
        "event_name": parsed.event_name,
        "ordinal": parsed.ordinal,
        "due_date": parsed.due_date.isoformat() if parsed.due_date is not None else None,
        "due_time": parsed.due_time.isoformat() if parsed.due_time is not None else None,
        "time_precision": parsed.time_precision or "datetime",
    }


def _proposal_delta_seconds(*, row: Change, candidate_after_payload: dict) -> int | None:
    before_payload = row.before_semantic_json if isinstance(row.before_semantic_json, dict) else None
    if before_payload is None:
        return None
    return semantic_delta_seconds(before_payload=before_payload, after_payload=candidate_after_payload)


def _load_latest_family_labels_for_payloads(
    *,
    db: Session,
    user_id: int,
    payloads: list[dict],
) -> dict[int, str]:
    family_ids = {
        family_id
        for family_id in (_payload_family_id(payload) for payload in payloads)
        if isinstance(family_id, int)
    }
    return load_latest_family_labels(db, user_id=user_id, family_ids=family_ids)


def _payload_family_id(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    family_id = payload.get("family_id")
    return family_id if isinstance(family_id, int) else None


def _resolve_family_name_override(*, payload: dict | None, latest_family_labels: dict[int, str]) -> str | None:
    if payload is None:
        return None
    family_id = _payload_family_id(payload)
    payload_uid = payload.get("uid") if isinstance(payload.get("uid"), str) and payload.get("uid").strip() else "unknown"
    return require_latest_family_label(
        family_id=family_id,
        latest_family_labels=latest_family_labels,
        context=f"review_changes.edit_service entity_uid={payload_uid}",
    )


__all__ = [
    "ReviewEditInvalidStateError",
    "ReviewEditNotFoundError",
    "ReviewEditValidationError",
    "apply_review_edit",
    "load_review_edit_context",
    "preview_review_edit",
]
