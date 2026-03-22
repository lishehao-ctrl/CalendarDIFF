from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import SourceEventObservation
from app.modules.runtime.apply.source_facts_coercion import coerce_calendar_payload
from app.modules.runtime.apply.observation_store import deactivate_observation
from app.modules.runtime.apply.unresolved_store import resolve_active_unresolved_records
from app.modules.runtime.apply.payload_contracts import PayloadContractError, validate_calendar_payload
from app.modules.runtime.apply.payload_extractors import (
    extract_course_parse,
    extract_semantic_event_draft,
    extract_source_facts_from_calendar_payload,
)
from app.modules.runtime.apply.semantic_observation_apply import apply_semantic_observation_candidate
from app.modules.runtime.connectors.ics_delta import external_event_id_from_component_key


def apply_calendar_observations(
    *,
    db: Session,
    source: InputSource,
    records: list[dict],
    applied_at: datetime,
    request_id: str,
    previous_observation_payloads: dict[str, dict] | None = None,
) -> set[str]:
    affected_entity_uids: set[str] = set()
    seen_external_ids: set[str] = set()
    delta_mode = False

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        record_type = record.get("record_type")
        if record_type not in {"calendar.event.extracted", "calendar.event.removed"}:
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            if record_type == "calendar.event.extracted":
                raise RuntimeError(f"calendar record payload at index {index} must be object")
            continue
        if record_type == "calendar.event.extracted":
            try:
                validate_calendar_payload(payload=payload, record_index=index)
            except PayloadContractError as exc:
                raise RuntimeError(str(exc)) from exc

        if record_type == "calendar.event.removed":
            delta_mode = True
            external_event_id = resolve_calendar_external_event_id(payload=payload)
            if external_event_id is None:
                continue
            existing_row = db.scalar(
                select(SourceEventObservation).where(
                    SourceEventObservation.source_id == source.id,
                    SourceEventObservation.external_event_id == external_event_id,
                )
            )
            if (
                existing_row is not None
                and isinstance(previous_observation_payloads, dict)
                and isinstance(existing_row.event_payload, dict)
            ):
                previous_observation_payloads.setdefault(existing_row.entity_uid, dict(existing_row.event_payload))
            affected_entity_uids.update(
                deactivate_observation(
                    db=db,
                    source_id=source.id,
                    external_event_id=external_event_id,
                    applied_at=applied_at,
                    request_id=request_id,
                )
            )
            resolve_active_unresolved_records(
                db=db,
                user_id=source.user_id,
                source_id=source.id,
                external_event_id=external_event_id,
                resolved_at=applied_at,
            )
            continue

        event = coerce_calendar_payload(payload=payload)
        resolved_external_event_id = resolve_calendar_external_event_id(payload=payload)
        external_event_id = resolved_external_event_id or event.uid
        if resolved_external_event_id is not None:
            delta_mode = True
        if external_event_id != event.uid:
            delta_mode = True
        source_facts = extract_source_facts_from_calendar_payload(
            payload=payload,
            external_event_id=external_event_id,
        )
        existing_row = db.scalar(
            select(SourceEventObservation).where(
                SourceEventObservation.source_id == source.id,
                SourceEventObservation.external_event_id == external_event_id,
            )
        )
        if (
            existing_row is not None
            and isinstance(previous_observation_payloads, dict)
            and isinstance(existing_row.event_payload, dict)
        ):
            previous_observation_payloads.setdefault(existing_row.entity_uid, dict(existing_row.event_payload))
        course_parse = extract_course_parse(payload=payload, source_facts=source_facts)
        semantic_draft = extract_semantic_event_draft(payload=payload, source_facts=source_facts)
        changed_entity_uids = apply_semantic_observation_candidate(
            db=db,
            source=source,
            external_event_id=external_event_id,
            source_facts=source_facts,
            semantic_draft=semantic_draft,
            course_parse=course_parse,
            link_signals={},
            raw_payload=payload,
            applied_at=applied_at,
            request_id=request_id,
            source_kind_value=SourceKind.CALENDAR.value,
            raw_ics_component_b64=payload.get("raw_ics_component_b64") if isinstance(payload.get("raw_ics_component_b64"), str) else None,
        )
        seen_external_ids.add(external_event_id)
        affected_entity_uids.update(changed_entity_uids)

    if delta_mode:
        return affected_entity_uids

    active_rows = db.scalars(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.is_active.is_(True),
        )
    ).all()
    for row in active_rows:
        if row.external_event_id in seen_external_ids:
            continue
        if isinstance(previous_observation_payloads, dict) and isinstance(row.event_payload, dict):
            previous_observation_payloads.setdefault(row.entity_uid, dict(row.event_payload))
        row.is_active = False
        row.observed_at = applied_at
        row.last_request_id = request_id
        affected_entity_uids.add(row.entity_uid)

    return affected_entity_uids


def resolve_calendar_external_event_id(*, payload: dict) -> str | None:
    external_event_id = payload.get("external_event_id")
    if isinstance(external_event_id, str) and external_event_id.strip():
        return external_event_id.strip()

    component_key = payload.get("component_key")
    if isinstance(component_key, str) and component_key.strip():
        return external_event_id_from_component_key(component_key.strip())
    return None


__all__ = ["apply_calendar_observations", "resolve_calendar_external_event_id"]
