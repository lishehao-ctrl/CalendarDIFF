from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.notify import Notification, NotificationChannel, NotificationStatus
from app.db.models.review import Change, ChangeIntakePhase, ChangeReviewBucket, ChangeSourceRef, ReviewStatus
from app.modules.common.event_display import event_display_dict, user_facing_event_view
from app.modules.common.family_labels import load_latest_family_labels, require_latest_family_label
from app.modules.changes.decision_support import build_change_decision_support
from app.modules.changes.change_projection import build_change_projection_context


def list_changes(
    db: Session,
    *,
    user_id: int,
    review_status: str,
    review_bucket: str,
    intake_phase: str,
    source_id: int | None,
    limit: int,
    offset: int,
    language_code: str | None = None,
) -> list[dict]:
    stmt = _base_change_query(user_id=user_id)
    if review_status == "pending":
        stmt = stmt.where(Change.review_status == ReviewStatus.PENDING)
    elif review_status == "approved":
        stmt = stmt.where(Change.review_status == ReviewStatus.APPROVED)
    elif review_status == "rejected":
        stmt = stmt.where(Change.review_status == ReviewStatus.REJECTED)
    if review_bucket == "initial_review":
        stmt = stmt.where(Change.review_bucket == ChangeReviewBucket.INITIAL_REVIEW)
    elif review_bucket == "changes":
        stmt = stmt.where(Change.review_bucket == ChangeReviewBucket.CHANGES)
    if intake_phase == "baseline":
        stmt = stmt.where(Change.intake_phase == ChangeIntakePhase.BASELINE)
    elif intake_phase == "replay":
        stmt = stmt.where(Change.intake_phase == ChangeIntakePhase.REPLAY)
    if source_id is not None:
        stmt = stmt.where(Change.source_refs.any(ChangeSourceRef.source_id == source_id))

    stmt = stmt.order_by(Change.detected_at.desc(), Change.id.desc()).offset(offset).limit(limit)
    rows = db.execute(stmt).all()
    return _serialize_rows(
        db=db,
        user_id=user_id,
        rows=rows,
        now=datetime.now(timezone.utc),
        language_code=language_code,
    )


def get_change(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    language_code: str | None = None,
) -> dict | None:
    row = db.execute(_base_change_query(user_id=user_id).where(Change.id == change_id).limit(1)).first()
    if row is None:
        return None
    items = _serialize_rows(
        db=db,
        user_id=user_id,
        rows=[row],
        now=datetime.now(timezone.utc),
        language_code=language_code,
    )
    return items[0] if items else None


def _base_change_query(*, user_id: int):
    return (
        select(Change, Notification)
        .options(selectinload(Change.source_refs))
        .outerjoin(
            Notification,
            and_(
                Notification.change_id == Change.id,
                Notification.channel == NotificationChannel.EMAIL,
            ),
        )
        .where(Change.user_id == user_id)
    )


def _serialize_rows(
    *,
    db: Session,
    user_id: int,
    rows: list[tuple[Change, Notification | None]],
    now: datetime,
    language_code: str | None = None,
) -> list[dict]:
    changes = [change for change, _notification in rows]
    projection = build_change_projection_context(db, user_id=user_id, changes=changes)
    family_ids = {
        family_id
        for change in changes
        for family_id in (
            _payload_family_id(change.before_semantic_json),
            _payload_family_id(change.after_semantic_json),
        )
        if isinstance(family_id, int)
    }
    latest_family_labels = load_latest_family_labels(db, user_id=user_id, family_ids=family_ids)
    output: list[dict] = []

    for change, notification in rows:
        proposal_sources = [row.model_dump(mode="json") for row in projection.proposal_sources(change)]
        primary_source = projection.primary_source(change)
        resolved_source_kind = primary_source.get("source_kind") if isinstance(primary_source, dict) else None
        priority_rank = 0 if resolved_source_kind == "email" else 1
        priority_label = "high" if priority_rank == 0 else "normal"
        before_payload = change.before_semantic_json if isinstance(change.before_semantic_json, dict) else None
        after_payload = change.after_semantic_json if isinstance(change.after_semantic_json, dict) else None
        notification_state, deliver_after = _read_notification_state(notification, now=now)
        change_summary = projection.change_summary(change).model_dump(mode="json")
        decision_support = build_change_decision_support(
            change=change,
            primary_source=primary_source,
            change_summary=change_summary,
            language_code=language_code,
        )
        before_family_name_override = _resolve_family_name_override(
            payload=before_payload,
            latest_family_labels=latest_family_labels,
        )
        after_family_name_override = _resolve_family_name_override(
            payload=after_payload,
            latest_family_labels=latest_family_labels,
        )

        output.append(
            {
                "id": change.id,
                "entity_uid": change.entity_uid,
                "change_type": change.change_type.value,
                "change_origin": change.change_origin.value,
                "intake_phase": change.intake_phase.value,
                "review_bucket": change.review_bucket.value,
                "detected_at": change.detected_at,
                "review_status": change.review_status.value,
                "before_display": (
                    event_display_dict(before_payload, strict=False, family_name_override=before_family_name_override)
                    if before_payload is not None
                    else None
                ),
                "after_display": (
                    event_display_dict(after_payload, strict=False, family_name_override=after_family_name_override)
                    if after_payload is not None
                    else None
                ),
                "before_event": (
                    user_facing_event_view(before_payload, strict=False, family_name_override=before_family_name_override)
                    if before_payload is not None
                    else None
                ),
                "after_event": (
                    user_facing_event_view(after_payload, strict=False, family_name_override=after_family_name_override)
                    if after_payload is not None
                    else None
                ),
                "primary_source": primary_source,
                "proposal_sources": proposal_sources,
                "viewed_at": change.viewed_at,
                "viewed_note": change.viewed_note,
                "reviewed_at": change.reviewed_at,
                "review_note": change.review_note,
                "priority_rank": priority_rank,
                "priority_label": priority_label,
                "notification_state": notification_state,
                "deliver_after": deliver_after,
                "change_summary": change_summary,
                "evidence_availability": {
                    "before": isinstance(change.before_evidence_json, dict),
                    "after": isinstance(change.after_evidence_json, dict),
                },
                "decision_support": decision_support,
            }
        )

    return output


def _read_notification_state(
    row: Notification | None,
    *,
    now: datetime,
) -> tuple[str | None, datetime | None]:
    if row is None:
        return None, None

    deliver_after = row.deliver_after
    if row.status == NotificationStatus.PENDING:
        if deliver_after > now and row.enqueue_reason == "email_priority_delay":
            return "queued_delayed_by_email_priority", deliver_after
        if deliver_after > now:
            return "queued_delayed", deliver_after
        return "queued", deliver_after
    if row.status == NotificationStatus.SENT:
        return "sent", deliver_after
    if row.status == NotificationStatus.FAILED:
        return "failed", deliver_after
    return None, deliver_after


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
        context=f"changes.change_listing entity_uid={payload_uid}",
    )


__all__ = [
    "get_change",
    "list_changes",
]
