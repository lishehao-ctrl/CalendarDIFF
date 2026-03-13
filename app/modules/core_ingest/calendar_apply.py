from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import SourceEventObservation
from app.modules.core_ingest.source_facts_coercion import coerce_calendar_payload
from app.modules.core_ingest.linking_engine import find_existing_entity_link
from app.modules.core_ingest.semantic_event_service import build_semantic_event_payload
from app.modules.core_ingest.observation_store import deactivate_observation, upsert_observation
from app.modules.core_ingest.payload_contracts import PayloadContractError, validate_calendar_payload
from app.modules.core_ingest.payload_extractors import (
    extract_enrichment_course_parse,
    extract_link_signals,
    extract_semantic_event_draft,
    extract_source_facts_from_calendar_payload,
)
from app.modules.core_ingest.course_work_item_family_resolution import build_source_scoped_entity_uid, resolve_kind_resolution
from app.modules.ingestion.ics_delta import external_event_id_from_component_key

logger = logging.getLogger(__name__)


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
        course_parse = extract_enrichment_course_parse(payload=payload)
        semantic_draft = extract_semantic_event_draft(payload=payload, source_facts=source_facts)
        link_signals = extract_link_signals(payload=payload, source_facts=source_facts)
        confidence = float(semantic_draft.get("confidence") or 0.0)
        kind_resolution = resolve_kind_resolution(
            db,
            user_id=source.user_id,
            course_parse=course_parse,
            semantic_parse=semantic_draft,
            source_kind=SourceKind.CALENDAR.value,
            external_event_id=external_event_id,
            source_id=source.id,
            request_id=request_id,
            provider=source.provider,
        )
        existing_link = find_existing_entity_link(
            db=db,
            user_id=source.user_id,
            source_id=source.id,
            external_event_id=external_event_id,
        )
        entity_uid = (
            existing_link.entity_uid
            if existing_link is not None and isinstance(existing_link.entity_uid, str)
            else build_source_scoped_entity_uid(source_kind=SourceKind.CALENDAR.value, external_event_id=external_event_id)
        )
        semantic_event = build_semantic_event_payload(
            semantic_draft=semantic_draft,
            source_facts=source_facts,
            family_id=kind_resolution.get("family_id") if isinstance(kind_resolution.get("family_id"), int) else None,
            family_name=kind_resolution.get("canonical_label") if isinstance(kind_resolution.get("canonical_label"), str) else None,
            raw_type=kind_resolution.get("raw_type") if isinstance(kind_resolution.get("raw_type"), str) else None,
            entity_uid=entity_uid,
        )
        semantic_event["uid"] = entity_uid
        logger.debug(
            "core_ingest.observation.calendar request_id=%s source_id=%s entity_uid=%s external_event_id=%s",
            request_id,
            source.id,
            entity_uid,
            external_event_id,
        )
        observation_payload = {
            "kind_resolution": kind_resolution,
            "source_facts": source_facts,
            "semantic_event": semantic_event,
            "link_signals": link_signals,
        }
        raw_ics_component_b64 = payload.get("raw_ics_component_b64")
        if isinstance(raw_ics_component_b64, str) and raw_ics_component_b64:
            observation_payload["raw_ics_component_b64"] = raw_ics_component_b64
        seen_external_ids.add(external_event_id)
        affected_entity_uids.update(
            upsert_observation(
                db=db,
                source=source,
                external_event_id=external_event_id,
                entity_uid=entity_uid,
                event_payload=observation_payload,
                applied_at=applied_at,
                request_id=request_id,
            )
        )

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
