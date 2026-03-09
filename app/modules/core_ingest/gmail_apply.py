from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import EventLinkOrigin
from app.modules.core_ingest.canonical_coercion import parse_optional_iso_datetime
from app.modules.core_ingest.entity_profile import get_or_create_event_entity, update_event_entity_course_profile
from app.modules.core_ingest.linking_engine import (
    find_existing_entity_link,
    resolve_pending_link_candidates_for_pair,
    upsert_event_entity_link,
)
from app.modules.core_ingest.observation_store import deactivate_observation, upsert_observation
from app.modules.core_ingest.payload_contracts import PayloadContractError, validate_gmail_payload_v3
from app.modules.core_ingest.payload_extractors import (
    extract_enrichment_course_parse,
    extract_enrichment_event_parts,
    extract_enrichment_work_item_parse,
    extract_link_signals,
    extract_source_canonical_from_gmail_payload,
)
from app.modules.core_ingest.work_item_kind_resolution import build_source_scoped_entity_uid, resolve_kind_resolution

logger = logging.getLogger(__name__)


def apply_gmail_observations(
    *,
    db: Session,
    source: InputSource,
    records: list[dict],
    applied_at: datetime,
    request_id: str,
    auto_link_contexts: list[dict] | None = None,
) -> set[str]:
    affected_entity_uids: set[str] = set()

    for index, record in enumerate(records):
        if not isinstance(record, dict) or record.get("record_type") != "gmail.message.extracted":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        try:
            validate_gmail_payload_v3(payload=payload, record_index=index)
        except PayloadContractError as exc:
            raise RuntimeError(str(exc)) from exc

        message_id = payload.get("message_id")
        if not isinstance(message_id, str) or not message_id.strip():
            continue
        external_event_id = message_id.strip()
        source_canonical = extract_source_canonical_from_gmail_payload(payload=payload)
        due_at = parse_optional_iso_datetime(source_canonical.get("source_dtstart_utc"))
        if due_at is None:
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

        course_parse = extract_enrichment_course_parse(payload=payload)
        work_item_parse = extract_enrichment_work_item_parse(payload=payload)
        event_parts = extract_enrichment_event_parts(payload=payload)
        link_signals = extract_link_signals(
            payload=payload,
            source_canonical=source_canonical,
        )
        confidence = float(course_parse.get("confidence") or work_item_parse.get("confidence") or 0.0)
        kind_resolution = resolve_kind_resolution(
            db,
            user_id=source.user_id,
            course_parse=course_parse,
            work_item_parse=work_item_parse,
            source_kind=SourceKind.EMAIL.value,
            external_event_id=external_event_id,
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
            else str(kind_resolution.get("entity_uid") or build_source_scoped_entity_uid(source_kind=SourceKind.EMAIL.value, external_event_id=external_event_id))
        )

        if existing_link is None:
            link_row = upsert_event_entity_link(
                db=db,
                source=source,
                external_event_id=external_event_id,
                entity_uid=entity_uid,
                link_origin=EventLinkOrigin.AUTO,
                link_score=1.0 if kind_resolution.get("status") == "resolved" else 0.2,
                signals_json=link_signals,
            )
            resolve_pending_link_candidates_for_pair(
                db=db,
                user_id=source.user_id,
                source_id=source.id,
                external_event_id=external_event_id,
                note="semantic_link_resolved",
            )
            if auto_link_contexts is not None and kind_resolution.get("status") == "resolved":
                auto_link_contexts.append(
                    {
                        "user_id": source.user_id,
                        "source_id": source.id,
                        "external_event_id": external_event_id,
                        "entity_uid": entity_uid,
                        "link_row": link_row,
                        "evidence_snapshot": {
                            "request_id": request_id,
                            "source_id": source.id,
                            "external_event_id": external_event_id,
                            "entity_uid": entity_uid,
                            "kind_resolution": kind_resolution,
                            "source_dtstart_utc": source_canonical.get("source_dtstart_utc"),
                        },
                    }
                )

        entity = get_or_create_event_entity(db=db, user_id=source.user_id, entity_uid=entity_uid)
        course_label = update_event_entity_course_profile(
            entity=entity,
            source_kind=SourceKind.EMAIL.value,
            course_parse=course_parse,
            source_title=source_canonical.get("source_title"),
        )
        logger.debug(
            "core_ingest.merge.gmail request_id=%s source_id=%s entity_uid=%s external_event_id=%s resolution=%s",
            request_id,
            source.id,
            entity_uid,
            external_event_id,
            kind_resolution.get("status"),
        )

        observation_payload = {
            "uid": entity_uid,
            "title": str(source_canonical.get("source_title") or f"Email event {external_event_id}")[:512],
            "course_label": course_label,
            "start_at_utc": str(source_canonical.get("source_dtstart_utc") or due_at.isoformat()),
            "end_at_utc": str(source_canonical.get("source_dtend_utc") or (due_at + timedelta(hours=1)).isoformat()),
            "confidence": confidence,
            "raw_confidence": confidence,
            "message_id": external_event_id,
            "kind_resolution": kind_resolution,
            "source_canonical": source_canonical,
            "enrichment": {
                "course_parse": course_parse,
                "work_item_parse": work_item_parse,
                "event_parts": event_parts,
                "link_signals": link_signals,
                "payload_schema_version": "obs_v3",
            },
        }

        affected_entity_uids.update(
            upsert_observation(
                db=db,
                source=source,
                external_event_id=external_event_id,
                merge_key=entity_uid,
                event_payload=observation_payload,
                applied_at=applied_at,
                request_id=request_id,
            )
        )

    return affected_entity_uids


__all__ = ["apply_gmail_observations"]
