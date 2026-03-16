from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import SourceEventObservation

__all__ = [
    "compute_payload_hash",
    "deactivate_observation",
    "normalize_observation_payload",
    "retire_active_observation_for_unresolved_transition",
    "semantic_payload_for_change_detection",
    "upsert_observation",
]

_RUNTIME_OBSERVATION_KEYS = ("source_facts", "semantic_event", "link_signals", "kind_resolution")


def upsert_observation(
    *,
    db: Session,
    source: InputSource,
    external_event_id: str,
    entity_uid: str,
    event_payload: dict,
    applied_at: datetime,
    request_id: str,
) -> set[str]:
    affected_entity_uids: set[str] = set()
    normalized_payload = normalize_observation_payload(event_payload)
    row = db.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.external_event_id == external_event_id,
        )
    )
    full_hash = compute_payload_hash(normalized_payload)

    if row is None:
        db.add(
            SourceEventObservation(
                user_id=source.user_id,
                source_id=source.id,
                source_kind=source.source_kind,
                provider=source.provider,
                external_event_id=external_event_id,
                entity_uid=entity_uid,
                event_payload=normalized_payload,
                event_hash=full_hash,
                observed_at=applied_at,
                is_active=True,
                last_request_id=request_id,
            )
        )
        affected_entity_uids.add(entity_uid)
        return affected_entity_uids

    old_entity_uid = row.entity_uid
    old_payload = row.event_payload if isinstance(row.event_payload, dict) else {}
    semantic_changed = semantic_payload_for_change_detection(old_payload) != semantic_payload_for_change_detection(normalized_payload)
    canonical_changed = old_entity_uid != entity_uid or semantic_changed or row.is_active is not True
    row.entity_uid = entity_uid
    row.event_payload = normalized_payload
    row.event_hash = full_hash
    row.observed_at = applied_at
    row.is_active = True
    row.last_request_id = request_id
    if canonical_changed:
        affected_entity_uids.add(old_entity_uid)
        affected_entity_uids.add(entity_uid)
    return affected_entity_uids


def normalize_observation_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise RuntimeError("core_ingest_payload_invalid: observation payload must be object")
    if "semantic_event_draft" in payload or "enrichment" in payload:
        raise RuntimeError("core_ingest_payload_invalid: observation payload must use runtime semantic_event envelope")

    normalized: dict[str, object] = {}
    for key in _RUNTIME_OBSERVATION_KEYS:
        value = payload.get(key)
        if key == "link_signals" and value is None:
            normalized[key] = {}
            continue
        if not isinstance(value, dict):
            raise RuntimeError(f"core_ingest_payload_invalid: observation payload missing {key}")
        normalized[key] = dict(value)

    raw_ics_component_b64 = payload.get("raw_ics_component_b64")
    if isinstance(raw_ics_component_b64, str) and raw_ics_component_b64:
        normalized["raw_ics_component_b64"] = raw_ics_component_b64
    return normalized


def semantic_payload_for_change_detection(payload: dict) -> dict:
    semantic_event = payload.get("semantic_event")
    if isinstance(semantic_event, dict):
        return semantic_event
    return {}


def deactivate_observation(
    *,
    db: Session,
    source_id: int,
    external_event_id: str,
    applied_at: datetime,
    request_id: str,
) -> set[str]:
    row = db.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source_id,
            SourceEventObservation.external_event_id == external_event_id,
        )
    )
    if row is None:
        return set()
    row.is_active = False
    row.observed_at = applied_at
    row.last_request_id = request_id
    return {row.entity_uid}


def retire_active_observation_for_unresolved_transition(
    *,
    db: Session,
    source_id: int,
    external_event_id: str,
    applied_at: datetime,
    request_id: str,
) -> bool:
    row = db.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source_id,
            SourceEventObservation.external_event_id == external_event_id,
            SourceEventObservation.is_active.is_(True),
        )
    )
    if row is None:
        return False
    row.is_active = False
    row.observed_at = applied_at
    row.last_request_id = request_id
    return True


def compute_payload_hash(payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
