from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import SourceEventObservation
from app.modules.core_ingest.entity_profile import append_alias

__all__ = [
    "apply_title_degradation_guard",
    "canonical_payload_for_hash",
    "compute_payload_hash",
    "deactivate_observation",
    "extract_observation_title_and_times",
    "normalize_observation_payload",
    "title_information_score",
    "upsert_observation",
]


def upsert_observation(
    *,
    db: Session,
    source: InputSource,
    external_event_id: str,
    merge_key: str,
    event_payload: dict,
    applied_at: datetime,
    request_id: str,
) -> set[str]:
    affected_merge_keys: set[str] = set()
    normalized_payload = normalize_observation_payload(event_payload)
    row = db.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.external_event_id == external_event_id,
        )
    )
    if row is not None:
        normalized_payload = apply_title_degradation_guard(old_payload=row.event_payload, new_payload=normalized_payload)

    canonical_hash = compute_payload_hash(canonical_payload_for_hash(normalized_payload))
    full_hash = compute_payload_hash(normalized_payload)
    normalized_payload["_canonical_hash"] = canonical_hash
    normalized_payload["_full_hash"] = full_hash

    if row is None:
        db.add(
            SourceEventObservation(
                user_id=source.user_id,
                source_id=source.id,
                source_kind=source.source_kind,
                provider=source.provider,
                external_event_id=external_event_id,
                merge_key=merge_key,
                event_payload=normalized_payload,
                event_hash=full_hash,
                observed_at=applied_at,
                is_active=True,
                last_request_id=request_id,
            )
        )
        affected_merge_keys.add(merge_key)
        return affected_merge_keys

    old_merge_key = row.merge_key
    old_payload = row.event_payload if isinstance(row.event_payload, dict) else {}
    old_canonical_payload = canonical_payload_for_hash(old_payload)
    new_canonical_payload = canonical_payload_for_hash(normalized_payload)
    canonical_changed = (
        old_merge_key != merge_key
        or old_canonical_payload != new_canonical_payload
        or row.is_active is not True
    )
    row.merge_key = merge_key
    row.event_payload = normalized_payload
    row.event_hash = full_hash
    row.observed_at = applied_at
    row.is_active = True
    row.last_request_id = request_id
    if canonical_changed:
        affected_merge_keys.add(old_merge_key)
        affected_merge_keys.add(merge_key)
    return affected_merge_keys


def normalize_observation_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    return dict(payload)


def canonical_payload_for_hash(payload: dict) -> dict:
    source_canonical = payload.get("source_canonical")
    if isinstance(source_canonical, dict):
        return source_canonical
    return {}


def apply_title_degradation_guard(*, old_payload: object, new_payload: dict) -> dict:
    old = old_payload if isinstance(old_payload, dict) else {}
    old_fields = extract_observation_title_and_times(old)
    new_fields = extract_observation_title_and_times(new_payload)
    if old_fields is None or new_fields is None:
        return new_payload
    old_title, old_start, old_end = old_fields
    new_title, new_start, new_end = new_fields
    if old_start != new_start or old_end != new_end:
        return new_payload
    if title_information_score(new_title) >= title_information_score(old_title):
        return new_payload

    adjusted = dict(new_payload)
    source_canonical_raw = adjusted.get("source_canonical")
    source_canonical = source_canonical_raw if isinstance(source_canonical_raw, dict) else {}
    source_canonical["source_title"] = old_title
    source_canonical["source_summary"] = old_title
    adjusted["source_canonical"] = source_canonical
    enrichment_raw = adjusted.get("enrichment")
    enrichment = enrichment_raw if isinstance(enrichment_raw, dict) else {}
    enrichment["title_aliases"] = append_alias(enrichment.get("title_aliases"), new_title, limit=24)
    adjusted["enrichment"] = enrichment
    return adjusted


def extract_observation_title_and_times(payload: dict) -> tuple[str, str, str] | None:
    source_canonical_raw = payload.get("source_canonical")
    source_canonical = source_canonical_raw if isinstance(source_canonical_raw, dict) else {}
    title = source_canonical.get("source_title")
    start = source_canonical.get("source_dtstart_utc")
    end = source_canonical.get("source_dtend_utc")
    if not isinstance(title, str) or not isinstance(start, str) or not isinstance(end, str):
        return None
    return title, start, end


def title_information_score(value: str) -> int:
    score = 0
    if re.search(r"\b[A-Z]{2,5}\s*[0-9]{1,3}[A-Z]\b", value, flags=re.I):
        score += 3
    elif re.search(r"\b[A-Z]{2,5}\s*[0-9]{1,3}\b", value, flags=re.I):
        score += 2
    if re.search(r"\b(WI|SP|SU|FA)\s*'?\d{2,4}\b", value, flags=re.I):
        score += 2
    if re.search(r"\b(exam|midterm|final)\b", value, flags=re.I):
        score += 1
    if re.search(r"\b(quiz|hw|homework|project|lab)\s*\d+\b", value, flags=re.I):
        score += 1
    return score


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
    return {row.merge_key}


def compute_payload_hash(payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
