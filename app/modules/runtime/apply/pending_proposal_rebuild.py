from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import (
    Change,
    ChangeIntakePhase,
    EventEntity,
    ReviewStatus,
    SourceEventObservation,
)
from app.modules.common.family_labels import load_latest_family_labels, resolve_family_label
from app.modules.common.payload_schemas import ApprovedSemanticPayload, ChangeSourceRefPayload
from app.modules.common.semantic_codec import (
    approved_entity_to_semantic_payload,
    parse_semantic_payload,
)
from app.modules.runtime.apply.pending_change_outbox import emit_change_pending_created_event
from app.modules.runtime.apply.proposal_decision import compute_pending_proposal_decision
from app.modules.runtime.apply.proposal_store import apply_pending_proposal_decision


def rebuild_pending_change_proposals(
    *,
    db: Session,
    user_id: int,
    source: InputSource,
    affected_entity_uids: set[str],
    applied_at: datetime,
    intake_phase: ChangeIntakePhase = ChangeIntakePhase.REPLAY,
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
        last_known_source_refs = (
            _load_last_known_source_refs(
                db=db,
                user_id=user_id,
                entity_uid=entity_uid,
            )
            if not observations
            else serialize_source_refs(observations)
        )

        decision = compute_pending_proposal_decision(
            entity_uid=entity_uid,
            observations=observations,
            existing_entity=existing_entity,
            existing_entity_payload=existing_entity_payload,
            previous_observation_payload=previous_observation_payloads.get(entity_uid)
            if isinstance(previous_observation_payloads, dict)
            else None,
            fallback_source_refs=last_known_source_refs,
            candidate_after_payload_fn=candidate_after_payload,
            serialize_source_refs_fn=serialize_source_refs,
        )
        new_change = apply_pending_proposal_decision(
            db=db,
            user_id=user_id,
            decision=decision,
            applied_at=applied_at,
            intake_phase=intake_phase,
        )
        if new_change is not None:
            created_changes.append(new_change)

    if created_changes:
        db.flush()
        emit_change_pending_created_event(
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


def _load_last_known_source_refs(
    *,
    db: Session,
    user_id: int,
    entity_uid: str,
) -> list[ChangeSourceRefPayload]:
    historical_rows = list(
        db.scalars(
            select(SourceEventObservation)
            .where(
                SourceEventObservation.user_id == user_id,
                SourceEventObservation.entity_uid == entity_uid,
            )
            .order_by(SourceEventObservation.observed_at.desc(), SourceEventObservation.id.desc())
        ).all()
    )
    return _last_known_source_refs_from_observations(historical_rows)


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


def _last_known_source_refs_from_observations(
    observations: Sequence[SourceEventObservation],
) -> list[ChangeSourceRefPayload]:
    rows: list[ChangeSourceRefPayload] = []
    seen_pairs: set[tuple[int, str]] = set()
    for row in observations:
        source_key = (int(row.source_id), str(row.external_event_id))
        if source_key in seen_pairs:
            continue
        seen_pairs.add(source_key)
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
    return rows


def candidate_after_payload(*, entity_uid: str, payload: dict) -> ApprovedSemanticPayload | None:
    semantic_event = payload.get("semantic_event") if isinstance(payload.get("semantic_event"), dict) else None
    if semantic_event is None:
        return None
    family_id = semantic_event.get("family_id")
    if not isinstance(family_id, int):
        raise RuntimeError(f"runtime_apply_integrity_error: semantic_event missing family_id for entity_uid={entity_uid}")
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
