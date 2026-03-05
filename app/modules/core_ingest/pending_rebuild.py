from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.db.models import (
    Change,
    ChangeType,
    Event,
    EventLinkAlertResolution,
    Input,
    InputSource,
    IntegrationOutbox,
    OutboxStatus,
    ReviewStatus,
    SourceEventObservation,
)
from app.modules.core_ingest.merge_engine import choose_primary_observation
from app.modules.core_ingest.serialization import (
    candidate_after_json,
    event_json_equivalent,
    event_row_to_json,
    safe_delta_seconds,
    serialize_proposal_sources,
)
from app.modules.review_links.alerts_service import (
    upsert_pending_link_alert,
)

__all__ = [
    "emit_review_pending_created_event",
    "pending_change_same",
    "rebuild_pending_change_proposals",
    "resolve_pending_change_as_rejected",
    "upsert_auto_link_alerts_without_pending",
    "upsert_pending_change",
]


def rebuild_pending_change_proposals(
    *,
    db: Session,
    source: InputSource,
    canonical_input: Input,
    affected_merge_keys: set[str],
    applied_at: datetime,
) -> tuple[int, set[str]]:
    created_changes: list[Change] = []

    for merge_key in sorted(affected_merge_keys):
        observations = db.scalars(
            select(SourceEventObservation).where(
                SourceEventObservation.user_id == source.user_id,
                SourceEventObservation.merge_key == merge_key,
                SourceEventObservation.is_active.is_(True),
            )
        ).all()

        primary = choose_primary_observation(
            [
                {
                    "source_kind": row.source_kind.value,
                    "event_payload": row.event_payload,
                    "observed_at": row.observed_at,
                }
                for row in observations
            ]
        )
        existing_event = db.scalar(
            select(Event).where(
                Event.input_id == canonical_input.id,
                Event.uid == merge_key,
            )
        )

        if primary is None and existing_event is None:
            resolve_pending_change_as_rejected(
                db=db,
                canonical_input_id=canonical_input.id,
                event_uid=merge_key,
                applied_at=applied_at,
                note="proposal_resolved_no_active_observation",
            )
            continue

        if primary is not None:
            primary_payload = primary.get("event_payload") if isinstance(primary.get("event_payload"), dict) else {}
            candidate_after = candidate_after_json(merge_key=merge_key, payload=primary_payload)
            if candidate_after is None:
                continue
            proposal_sources = serialize_proposal_sources(observations)

            if existing_event is None:
                new_change = upsert_pending_change(
                    db=db,
                    input_id=canonical_input.id,
                    event_uid=merge_key,
                    change_type=ChangeType.CREATED,
                    before_json=None,
                    after_json=candidate_after,
                    delta_seconds=None,
                    proposal_merge_key=merge_key,
                    proposal_sources_json=proposal_sources,
                    detected_at=applied_at,
                )
                if new_change is not None:
                    created_changes.append(new_change)
                continue

            before_json = event_row_to_json(existing_event)
            if event_json_equivalent(before_json, candidate_after):
                resolve_pending_change_as_rejected(
                    db=db,
                    canonical_input_id=canonical_input.id,
                    event_uid=merge_key,
                    applied_at=applied_at,
                    note="proposal_already_matches_canonical",
                )
                continue

            delta_seconds = safe_delta_seconds(before_json=before_json, after_json=candidate_after)
            new_change = upsert_pending_change(
                db=db,
                input_id=canonical_input.id,
                event_uid=merge_key,
                change_type=ChangeType.DUE_CHANGED,
                before_json=before_json,
                after_json=candidate_after,
                delta_seconds=delta_seconds,
                proposal_merge_key=merge_key,
                proposal_sources_json=proposal_sources,
                detected_at=applied_at,
            )
            if new_change is not None:
                created_changes.append(new_change)
            continue

        assert existing_event is not None
        before_json = event_row_to_json(existing_event)
        new_change = upsert_pending_change(
            db=db,
            input_id=canonical_input.id,
            event_uid=merge_key,
            change_type=ChangeType.REMOVED,
            before_json=before_json,
            after_json=None,
            delta_seconds=None,
            proposal_merge_key=merge_key,
            proposal_sources_json=[],
            detected_at=applied_at,
        )
        if new_change is not None:
            created_changes.append(new_change)

    if created_changes:
        db.flush()
        emit_review_pending_created_event(
            db=db,
            canonical_input_id=canonical_input.id,
            changes=created_changes,
            detected_at=applied_at,
        )

    pending_event_uids = set(
        db.scalars(
            select(Change.event_uid).where(
                Change.input_id == canonical_input.id,
                Change.review_status == ReviewStatus.PENDING,
                Change.event_uid.in_(sorted(affected_merge_keys)),
            )
        ).all()
    )
    return len(created_changes), pending_event_uids


def upsert_auto_link_alerts_without_pending(
    *,
    db: Session,
    auto_link_contexts: list[dict],
    pending_event_uids: set[str],
) -> None:
    for context in auto_link_contexts:
        entity_uid = context.get("entity_uid")
        if not isinstance(entity_uid, str) or not entity_uid.strip():
            continue
        if entity_uid in pending_event_uids:
            continue
        link_row = context.get("link_row")
        link_id = int(link_row.id) if isinstance(getattr(link_row, "id", None), int) else None
        upsert_pending_link_alert(
            db=db,
            user_id=int(context["user_id"]),
            source_id=int(context["source_id"]),
            external_event_id=str(context["external_event_id"]),
            entity_uid=entity_uid,
            link_id=link_id,
            evidence_snapshot=context.get("evidence_snapshot")
            if isinstance(context.get("evidence_snapshot"), dict)
            else {},
        )


def emit_review_pending_created_event(
    *,
    db: Session,
    canonical_input_id: int,
    changes: list[Change],
    detected_at: datetime,
) -> None:
    change_ids = [int(change.id) for change in changes if isinstance(change.id, int)]
    if not change_ids:
        return
    event = new_event(
        event_type="review.pending.created",
        aggregate_type="change_batch",
        aggregate_id=str(change_ids[0]),
        payload={
            "input_id": canonical_input_id,
            "change_ids": change_ids,
            "deliver_after": detected_at.isoformat(),
        },
    )
    db.add(
        IntegrationOutbox(
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload_json=event.payload,
            status=OutboxStatus.PENDING,
            available_at=event.available_at,
        )
    )


def upsert_pending_change(
    *,
    db: Session,
    input_id: int,
    event_uid: str,
    change_type: ChangeType,
    before_json: dict | None,
    after_json: dict | None,
    delta_seconds: int | None,
    proposal_merge_key: str,
    proposal_sources_json: list[dict],
    detected_at: datetime,
) -> Change | None:
    existing_pending = db.scalar(
        select(Change)
        .where(
            Change.input_id == input_id,
            Change.event_uid == event_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
        .order_by(Change.id.desc())
        .limit(1)
    )

    if existing_pending is None:
        change = Change(
            input_id=input_id,
            event_uid=event_uid,
            change_type=change_type,
            detected_at=detected_at,
            before_json=before_json,
            after_json=after_json,
            delta_seconds=delta_seconds,
            viewed_at=None,
            viewed_note=None,
            review_status=ReviewStatus.PENDING,
            reviewed_at=None,
            review_note=None,
            reviewed_by_user_id=None,
            proposal_merge_key=proposal_merge_key,
            proposal_sources_json=proposal_sources_json,
            before_snapshot_id=None,
            after_snapshot_id=None,
            evidence_keys=None,
        )
        db.add(change)
        db.flush()
        return change

    if pending_change_same(
        existing_pending,
        change_type=change_type,
        before_json=before_json,
        after_json=after_json,
        delta_seconds=delta_seconds,
        proposal_merge_key=proposal_merge_key,
        proposal_sources_json=proposal_sources_json,
    ):
        return None

    existing_pending.change_type = change_type
    existing_pending.detected_at = detected_at
    existing_pending.before_json = before_json
    existing_pending.after_json = after_json
    existing_pending.delta_seconds = delta_seconds
    existing_pending.viewed_at = None
    existing_pending.viewed_note = None
    existing_pending.review_status = ReviewStatus.PENDING
    existing_pending.reviewed_at = None
    existing_pending.review_note = None
    existing_pending.reviewed_by_user_id = None
    existing_pending.proposal_merge_key = proposal_merge_key
    existing_pending.proposal_sources_json = proposal_sources_json
    existing_pending.before_snapshot_id = None
    existing_pending.after_snapshot_id = None
    existing_pending.evidence_keys = None
    return None


def resolve_pending_change_as_rejected(
    *,
    db: Session,
    canonical_input_id: int,
    event_uid: str,
    applied_at: datetime,
    note: str,
) -> None:
    pending = db.scalars(
        select(Change).where(
            Change.input_id == canonical_input_id,
            Change.event_uid == event_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
    ).all()
    for row in pending:
        row.review_status = ReviewStatus.REJECTED
        row.reviewed_at = applied_at
        row.review_note = note
        row.reviewed_by_user_id = None


def pending_change_same(
    row: Change,
    *,
    change_type: ChangeType,
    before_json: dict | None,
    after_json: dict | None,
    delta_seconds: int | None,
    proposal_merge_key: str,
    proposal_sources_json: list[dict],
) -> bool:
    return (
        row.change_type == change_type
        and row.before_json == before_json
        and row.after_json == after_json
        and row.delta_seconds == delta_seconds
        and row.proposal_merge_key == proposal_merge_key
        and row.proposal_sources_json == proposal_sources_json
    )
