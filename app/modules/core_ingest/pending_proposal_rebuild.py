from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import Change, ChangeType, EventEntity, EventEntityLifecycle, ReviewStatus, SourceEventObservation
from app.modules.common.family_labels import load_latest_family_labels, resolve_family_label
from app.modules.common.payload_schemas import ApprovedSemanticPayload, ChangeSourceRefPayload, FrozenReviewEvidence
from app.modules.common.semantic_codec import (
    approved_entity_to_semantic_payload,
    parse_semantic_payload,
    semantic_delta_seconds,
    semantic_payloads_equivalent,
)
from app.modules.core_ingest.observation_priority import choose_primary_observation
from app.modules.core_ingest.pending_change_store import (
    resolve_pending_change_as_rejected,
    upsert_pending_change,
)
from app.modules.core_ingest.pending_review_outbox import emit_review_pending_created_event
from app.modules.core_ingest.review_evidence import freeze_observation_evidence, freeze_semantic_evidence
from app.modules.common.change_source_refs import primary_source_from_refs


@dataclass(frozen=True)
class PendingProposalDecision:
    mode: Literal["reject", "upsert", "skip"]
    entity_uid: str
    change_type: ChangeType | None = None
    before_semantic: ApprovedSemanticPayload | None = None
    after_semantic: ApprovedSemanticPayload | None = None
    delta_seconds: int | None = None
    source_refs: list[ChangeSourceRefPayload] = field(default_factory=list)
    before_evidence: FrozenReviewEvidence | None = None
    after_evidence: FrozenReviewEvidence | None = None
    reject_note: str | None = None


def rebuild_pending_change_proposals(
    *,
    db: Session,
    user_id: int,
    source: InputSource,
    affected_entity_uids: set[str],
    applied_at: datetime,
    previous_observation_payloads: dict[str, dict] | None = None,
) -> tuple[int, set[str]]:
    created_changes: list[Change] = []
    family_label_cache: dict[int, str] = {}

    for entity_uid in sorted(affected_entity_uids):
        observations = list(
            db.scalars(
                select(SourceEventObservation).where(
                    SourceEventObservation.user_id == source.user_id,
                    SourceEventObservation.entity_uid == entity_uid,
                    SourceEventObservation.is_active.is_(True),
                ).order_by(SourceEventObservation.observed_at.asc(), SourceEventObservation.id.asc())
            ).all()
        )
        existing_entity = db.scalar(
            select(EventEntity).where(
                EventEntity.user_id == user_id,
                EventEntity.entity_uid == entity_uid,
            )
        )
        existing_entity_payload = _approved_entity_payload(
            db=db,
            user_id=user_id,
            existing_entity=existing_entity,
            family_label_cache=family_label_cache,
        )

        decision = compute_pending_proposal_decision(
            entity_uid=entity_uid,
            observations=observations,
            existing_entity=existing_entity,
            existing_entity_payload=existing_entity_payload,
            previous_observation_payload=previous_observation_payloads.get(entity_uid)
            if isinstance(previous_observation_payloads, dict)
            else None,
        )
        new_change = apply_pending_proposal_decision(
            db=db,
            user_id=user_id,
            decision=decision,
            applied_at=applied_at,
        )
        if new_change is not None:
            created_changes.append(new_change)

    if created_changes:
        db.flush()
        emit_review_pending_created_event(
            db=db,
            user_id=user_id,
            changes=created_changes,
            detected_at=applied_at,
        )

    pending_entity_uids = set(
        db.scalars(
            select(Change.entity_uid).where(
                Change.user_id == user_id,
                Change.review_status == ReviewStatus.PENDING,
                Change.entity_uid.in_(sorted(affected_entity_uids)),
            )
        ).all()
    )
    return len(created_changes), pending_entity_uids


def compute_pending_proposal_decision(
    *,
    entity_uid: str,
    observations: Sequence[SourceEventObservation],
    existing_entity: EventEntity | None,
    existing_entity_payload: ApprovedSemanticPayload | None = None,
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

    if primary is None and (existing_entity is None or existing_entity.lifecycle != EventEntityLifecycle.ACTIVE):
        return PendingProposalDecision(
            mode="reject",
            entity_uid=entity_uid,
            reject_note="proposal_resolved_no_active_observation",
        )

    if primary is None:
        assert existing_entity_payload is not None
        return PendingProposalDecision(
            mode="upsert",
            entity_uid=entity_uid,
            change_type=ChangeType.REMOVED,
            before_semantic=existing_entity_payload,
            after_semantic=None,
            delta_seconds=None,
            source_refs=[],
            before_evidence=freeze_observation_evidence(
                provider=None,
                event_payload=previous_observation_payload,
                semantic_payload=existing_entity_payload.to_json_dict(),
            )
            or freeze_semantic_evidence(provider=None, semantic_payload=existing_entity_payload.to_json_dict()),
            after_evidence=None,
        )

    primary_payload_raw = primary.get("event_payload")
    primary_payload = primary_payload_raw if isinstance(primary_payload_raw, dict) else {}
    candidate_after = candidate_after_payload(entity_uid=entity_uid, payload=primary_payload)
    if candidate_after is None:
        return PendingProposalDecision(mode="skip", entity_uid=entity_uid)
    source_refs = serialize_source_refs(observations)
    primary_source_ref = primary_source_from_refs(source_refs)
    after_evidence = freeze_observation_evidence(
        provider=primary_source_ref.get("provider") if isinstance(primary_source_ref, dict) else None,
        event_payload=primary_payload,
        semantic_payload=candidate_after.to_json_dict(),
    ) or freeze_semantic_evidence(
        provider=primary_source_ref.get("provider") if isinstance(primary_source_ref, dict) else None,
        semantic_payload=candidate_after.to_json_dict(),
    )

    if existing_entity is None or existing_entity.lifecycle != EventEntityLifecycle.ACTIVE:
        return PendingProposalDecision(
            mode="upsert",
            entity_uid=entity_uid,
            change_type=ChangeType.CREATED,
            before_semantic=None,
            after_semantic=candidate_after,
            delta_seconds=None,
            source_refs=source_refs,
            before_evidence=None,
            after_evidence=after_evidence,
        )

    before_semantic = existing_entity_payload
    if before_semantic is None:
        return PendingProposalDecision(mode="skip", entity_uid=entity_uid)
    if semantic_payloads_equivalent(before_semantic, candidate_after):
        return PendingProposalDecision(
            mode="reject",
            entity_uid=entity_uid,
            reject_note="proposal_already_matches_approved_entity_state",
        )

    return PendingProposalDecision(
        mode="upsert",
        entity_uid=entity_uid,
        change_type=ChangeType.DUE_CHANGED,
        before_semantic=before_semantic,
        after_semantic=candidate_after,
        delta_seconds=semantic_delta_seconds(before_payload=before_semantic, after_payload=candidate_after),
        source_refs=source_refs,
        before_evidence=freeze_observation_evidence(
            provider=None,
            event_payload=previous_observation_payload,
            semantic_payload=before_semantic.to_json_dict(),
        )
        or freeze_semantic_evidence(provider=None, semantic_payload=before_semantic.to_json_dict()),
        after_evidence=after_evidence,
    )


def apply_pending_proposal_decision(
    *,
    db: Session,
    user_id: int,
    decision: PendingProposalDecision,
    applied_at: datetime,
) -> Change | None:
    if decision.mode == "skip":
        return None
    if decision.mode == "reject":
        resolve_pending_change_as_rejected(
            db=db,
            user_id=user_id,
            entity_uid=decision.entity_uid,
            applied_at=applied_at,
            note=decision.reject_note or "proposal_rejected",
        )
        return None

    if decision.change_type is None:
        raise RuntimeError("upsert decision requires change_type")
    return upsert_pending_change(
        db=db,
        user_id=user_id,
        entity_uid=decision.entity_uid,
        change_type=decision.change_type,
        before_semantic_json=decision.before_semantic.to_json_dict() if decision.before_semantic is not None else None,
        after_semantic_json=decision.after_semantic.to_json_dict() if decision.after_semantic is not None else None,
        delta_seconds=decision.delta_seconds,
        source_refs=[row.model_dump(mode="json") for row in decision.source_refs],
        detected_at=applied_at,
        before_evidence_json=decision.before_evidence.model_dump(mode="json") if decision.before_evidence is not None else None,
        after_evidence_json=decision.after_evidence.model_dump(mode="json") if decision.after_evidence is not None else None,
    )


__all__ = [
    "PendingProposalDecision",
    "apply_pending_proposal_decision",
    "compute_pending_proposal_decision",
    "rebuild_pending_change_proposals",
]


def serialize_source_refs(observations: Sequence[SourceEventObservation]) -> list[ChangeSourceRefPayload]:
    rows: list[ChangeSourceRefPayload] = []
    for row in observations:
        payload = row.event_payload if isinstance(row.event_payload, dict) else {}
        semantic_event = payload.get("semantic_event") if isinstance(payload.get("semantic_event"), dict) else {}
        confidence_raw = semantic_event.get("confidence") if isinstance(semantic_event, dict) else None
        confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0
        rows.append(
            ChangeSourceRefPayload(
                source_id=row.source_id,
                source_kind=row.source_kind.value,
                provider=row.provider,
                external_event_id=row.external_event_id,
                confidence=confidence,
            )
        )
    rows.sort(
        key=lambda item: (
            float(item.confidence or 0.0),
            2 if item.source_kind == "calendar" else 1 if item.source_kind == "email" else 0,
        ),
        reverse=True,
    )
    return rows


def candidate_after_payload(*, entity_uid: str, payload: dict) -> ApprovedSemanticPayload | None:
    semantic_event = payload.get("semantic_event") if isinstance(payload.get("semantic_event"), dict) else None
    if semantic_event is None:
        return None
    family_id = semantic_event.get("family_id")
    if not isinstance(family_id, int):
        raise RuntimeError(f"core_ingest_integrity_error: semantic_event missing family_id for entity_uid={entity_uid}")
    event_name = semantic_event.get("event_name")
    due_date = semantic_event.get("due_date")
    if not isinstance(event_name, str) or not event_name.strip() or not isinstance(due_date, str) or not due_date.strip():
        return None
    parsed = parse_semantic_payload(
        entity_uid,
        {
            "uid": entity_uid,
            "course_dept": semantic_event.get("course_dept"),
            "course_number": semantic_event.get("course_number"),
            "course_suffix": semantic_event.get("course_suffix"),
            "course_quarter": semantic_event.get("course_quarter"),
            "course_year2": semantic_event.get("course_year2"),
            "family_id": family_id,
            "family_name": semantic_event.get("family_name"),
            "raw_type": semantic_event.get("raw_type"),
            "event_name": event_name.strip()[:512],
            "ordinal": semantic_event.get("ordinal"),
            "due_date": due_date.strip(),
            "due_time": semantic_event.get("due_time"),
            "time_precision": semantic_event.get("time_precision") or "datetime",
        },
    )
    return parsed


def _approved_entity_payload(
    *,
    db: Session,
    user_id: int,
    existing_entity: EventEntity | None,
    family_label_cache: dict[int, str],
) -> ApprovedSemanticPayload | None:
    if existing_entity is None:
        return None
    if isinstance(existing_entity.family_id, int) and existing_entity.family_id not in family_label_cache:
        family_label_cache.update(load_latest_family_labels(db, user_id=user_id, family_ids=[existing_entity.family_id]))
    payload = approved_entity_to_semantic_payload(
        existing_entity,
        family_name_override=resolve_family_label(
            family_id=existing_entity.family_id,
            latest_family_labels=family_label_cache,
        ),
    )
    return parse_semantic_payload(existing_entity.entity_uid, payload)
