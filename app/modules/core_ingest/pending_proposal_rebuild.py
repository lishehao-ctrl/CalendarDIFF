from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import Change, ChangeType, Event, Input, ReviewStatus, SourceEventObservation
from app.modules.core_ingest.merge_engine import choose_primary_observation
from app.modules.core_ingest.pending_change_store import (
    resolve_pending_change_as_rejected,
    upsert_pending_change,
)
from app.modules.core_ingest.pending_review_outbox import emit_review_pending_created_event
from app.modules.core_ingest.serialization import (
    candidate_after_json,
    event_json_equivalent,
    event_row_to_json,
    safe_delta_seconds,
    serialize_proposal_sources,
)


@dataclass(frozen=True)
class PendingProposalDecision:
    mode: Literal["reject", "upsert", "skip"]
    event_uid: str
    change_type: ChangeType | None = None
    before_json: dict | None = None
    after_json: dict | None = None
    delta_seconds: int | None = None
    proposal_sources_json: list[dict] = field(default_factory=list)
    before_snapshot_payload: dict | None = None
    after_snapshot_payload: dict | None = None
    reject_note: str | None = None


def rebuild_pending_change_proposals(
    *,
    db: Session,
    source: InputSource,
    canonical_input: Input,
    affected_merge_keys: set[str],
    applied_at: datetime,
    previous_observation_payloads: dict[str, dict] | None = None,
) -> tuple[int, set[str]]:
    created_changes: list[Change] = []

    for merge_key in sorted(affected_merge_keys):
        observations = list(
            db.scalars(
                select(SourceEventObservation).where(
                    SourceEventObservation.user_id == source.user_id,
                    SourceEventObservation.merge_key == merge_key,
                    SourceEventObservation.is_active.is_(True),
                ).order_by(SourceEventObservation.observed_at.asc(), SourceEventObservation.id.asc())
            ).all()
        )
        existing_event = db.scalar(
            select(Event).where(
                Event.input_id == canonical_input.id,
                Event.uid == merge_key,
            )
        )

        decision = compute_pending_proposal_decision(
            merge_key=merge_key,
            observations=observations,
            existing_event=existing_event,
            previous_observation_payload=previous_observation_payloads.get(merge_key)
            if isinstance(previous_observation_payloads, dict)
            else None,
        )
        new_change = apply_pending_proposal_decision(
            db=db,
            canonical_input_id=canonical_input.id,
            decision=decision,
            applied_at=applied_at,
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


def compute_pending_proposal_decision(
    *,
    merge_key: str,
    observations: Sequence[SourceEventObservation],
    existing_event: Event | None,
    previous_observation_payload: dict | None = None,
) -> PendingProposalDecision:
    primary = choose_primary_observation(
        [
            {
                "source_kind": row.source_kind.value,
                "event_payload": row.event_payload,
                "observed_at": row.observed_at,
                "observation_id": int(row.id),
            }
            for row in observations
        ]
    )

    if primary is None and existing_event is None:
        return PendingProposalDecision(
            mode="reject",
            event_uid=merge_key,
            reject_note="proposal_resolved_no_active_observation",
        )

    if primary is None:
        assert existing_event is not None
        return PendingProposalDecision(
            mode="upsert",
            event_uid=merge_key,
            change_type=ChangeType.REMOVED,
            before_json=event_row_to_json(existing_event),
            after_json=None,
            delta_seconds=None,
            proposal_sources_json=[],
            before_snapshot_payload=previous_observation_payload,
            after_snapshot_payload=None,
        )

    primary_payload_raw = primary.get("event_payload")
    primary_payload = primary_payload_raw if isinstance(primary_payload_raw, dict) else {}
    candidate_after = candidate_after_json(merge_key=merge_key, payload=primary_payload)
    if candidate_after is None:
        return PendingProposalDecision(mode="skip", event_uid=merge_key)
    proposal_sources = serialize_proposal_sources(observations)

    if existing_event is None:
        return PendingProposalDecision(
            mode="upsert",
            event_uid=merge_key,
            change_type=ChangeType.CREATED,
            before_json=None,
            after_json=candidate_after,
            delta_seconds=None,
            proposal_sources_json=proposal_sources,
            before_snapshot_payload=None,
            after_snapshot_payload=primary_payload,
        )

    before_json = event_row_to_json(existing_event)
    if event_json_equivalent(before_json, candidate_after):
        return PendingProposalDecision(
            mode="reject",
            event_uid=merge_key,
            reject_note="proposal_already_matches_canonical",
        )

    return PendingProposalDecision(
        mode="upsert",
        event_uid=merge_key,
        change_type=ChangeType.DUE_CHANGED,
        before_json=before_json,
        after_json=candidate_after,
        delta_seconds=safe_delta_seconds(before_json=before_json, after_json=candidate_after),
        proposal_sources_json=proposal_sources,
        before_snapshot_payload=previous_observation_payload,
        after_snapshot_payload=primary_payload,
    )


def apply_pending_proposal_decision(
    *,
    db: Session,
    canonical_input_id: int,
    decision: PendingProposalDecision,
    applied_at: datetime,
) -> Change | None:
    if decision.mode == "skip":
        return None
    if decision.mode == "reject":
        resolve_pending_change_as_rejected(
            db=db,
            canonical_input_id=canonical_input_id,
            event_uid=decision.event_uid,
            applied_at=applied_at,
            note=decision.reject_note or "proposal_rejected",
        )
        return None

    if decision.change_type is None:
        raise RuntimeError("upsert decision requires change_type")
    return upsert_pending_change(
        db=db,
        input_id=canonical_input_id,
        event_uid=decision.event_uid,
        change_type=decision.change_type,
        before_json=decision.before_json,
        after_json=decision.after_json,
        delta_seconds=decision.delta_seconds,
        proposal_merge_key=decision.event_uid,
        proposal_sources_json=decision.proposal_sources_json,
        detected_at=applied_at,
        before_snapshot_payload=decision.before_snapshot_payload,
        after_snapshot_payload=decision.after_snapshot_payload,
    )


__all__ = [
    "PendingProposalDecision",
    "apply_pending_proposal_decision",
    "compute_pending_proposal_decision",
    "rebuild_pending_change_proposals",
]
