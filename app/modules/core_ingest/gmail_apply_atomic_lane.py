from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.input import InputSource, SourceKind
from app.modules.common.source_term_window import (
    parse_iso_datetime,
    parse_source_term_window,
    semantic_due_date_in_window,
    source_timezone_name,
)
from app.modules.core_ingest.entity_resolution import resolve_entity_uid
from app.modules.core_ingest.course_work_item_family_resolution import resolve_kind_resolution
from app.modules.core_ingest.observation_store import retire_active_observation_for_unresolved_transition, upsert_observation
from app.modules.core_ingest.payload_contracts import PayloadContractError, validate_gmail_payload
from app.modules.core_ingest.payload_extractors import (
    extract_course_parse,
    extract_link_signals,
    extract_semantic_event_draft,
    extract_source_facts_from_gmail_payload,
)
from app.modules.core_ingest.product_scope import is_monitored_assignment_or_exam_event
from app.modules.core_ingest.semantic_event_service import build_semantic_event_payload
from app.modules.core_ingest.unresolved_store import resolve_active_unresolved_records, upsert_active_unresolved_record

logger = logging.getLogger(__name__)


def apply_gmail_atomic_record(
    *,
    db: Session,
    source: InputSource,
    payload: dict,
    record_index: int,
    applied_at: datetime,
    request_id: str,
) -> set[str]:
    try:
        validate_gmail_payload(payload=payload, record_index=record_index)
    except PayloadContractError as exc:
        raise RuntimeError(str(exc)) from exc

    message_id = payload.get("message_id")
    if not isinstance(message_id, str) or not message_id.strip():
        return set()
    external_event_id = message_id.strip()
    source_facts = extract_source_facts_from_gmail_payload(payload=payload)

    course_parse = extract_course_parse(payload=payload, source_facts=source_facts)
    semantic_draft = extract_semantic_event_draft(payload=payload, source_facts=source_facts)
    link_signals = extract_link_signals(
        payload=payload,
        source_facts=source_facts,
    )
    term_window = parse_source_term_window(source, required=False)
    if term_window is not None and not semantic_due_date_in_window(
        semantic_payload=semantic_draft,
        fallback_datetime=parse_iso_datetime(source_facts.get("internal_date")),
        term_window=term_window,
        timezone_name=source_timezone_name(source),
    ):
        retire_active_observation_for_unresolved_transition(
            db=db,
            source_id=source.id,
            external_event_id=external_event_id,
            applied_at=applied_at,
            request_id=request_id,
        )
        upsert_active_unresolved_record(
            db=db,
            user_id=source.user_id,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id=external_event_id,
            request_id=request_id,
            reason_code="term_out_of_scope",
            source_facts_json=source_facts,
            semantic_event_draft_json=semantic_draft,
            kind_resolution_json=None,
            raw_payload_json=payload,
        )
        return set()
    if not is_monitored_assignment_or_exam_event(
        semantic_draft=semantic_draft,
        source_facts=source_facts,
    ):
        retire_active_observation_for_unresolved_transition(
            db=db,
            source_id=source.id,
            external_event_id=external_event_id,
            applied_at=applied_at,
            request_id=request_id,
        )
        upsert_active_unresolved_record(
            db=db,
            user_id=source.user_id,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id=external_event_id,
            request_id=request_id,
            reason_code="product_scope_excluded",
            source_facts_json=source_facts,
            semantic_event_draft_json=semantic_draft,
            kind_resolution_json=None,
            raw_payload_json=payload,
        )
        return set()
    kind_resolution = resolve_kind_resolution(
        db,
        user_id=source.user_id,
        course_parse=course_parse,
        semantic_parse=semantic_draft,
        source_facts=source_facts,
        source_kind=SourceKind.EMAIL.value,
        external_event_id=external_event_id,
        source_id=source.id,
        request_id=request_id,
        provider=source.provider,
    )
    if kind_resolution.get("status") == "unresolved":
        retire_active_observation_for_unresolved_transition(
            db=db,
            source_id=source.id,
            external_event_id=external_event_id,
            applied_at=applied_at,
            request_id=request_id,
        )
        upsert_active_unresolved_record(
            db=db,
            user_id=source.user_id,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id=external_event_id,
            request_id=request_id,
            reason_code=str(kind_resolution.get("reason_code") or "missing_course_identity"),
            source_facts_json=source_facts,
            semantic_event_draft_json=semantic_draft,
            kind_resolution_json=kind_resolution,
            raw_payload_json=payload,
        )
        return set()

    entity_resolution = resolve_entity_uid(
        db=db,
        external_event_id=external_event_id,
        source=source,
        course_parse=course_parse,
        kind_resolution=kind_resolution,
    )
    if entity_resolution.status != "resolved" or not isinstance(entity_resolution.entity_uid, str):
        retire_active_observation_for_unresolved_transition(
            db=db,
            source_id=source.id,
            external_event_id=external_event_id,
            applied_at=applied_at,
            request_id=request_id,
        )
        upsert_active_unresolved_record(
            db=db,
            user_id=source.user_id,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id=external_event_id,
            request_id=request_id,
            reason_code=str(entity_resolution.reason_code or "insufficient_entity_resolution"),
            source_facts_json=source_facts,
            semantic_event_draft_json=semantic_draft,
            kind_resolution_json=kind_resolution,
            raw_payload_json=payload,
        )
        return set()
    entity_uid = entity_resolution.entity_uid

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
        "core_ingest.observation.gmail request_id=%s source_id=%s entity_uid=%s external_event_id=%s resolution=%s",
        request_id,
        source.id,
        entity_uid,
        external_event_id,
        kind_resolution.get("status"),
    )
    observation_payload = {
        "kind_resolution": kind_resolution,
        "source_facts": source_facts,
        "semantic_event": semantic_event,
        "link_signals": link_signals,
    }

    changed_entity_uids = upsert_observation(
        db=db,
        source=source,
        external_event_id=external_event_id,
        entity_uid=entity_uid,
        event_payload=observation_payload,
        applied_at=applied_at,
        request_id=request_id,
    )
    resolve_active_unresolved_records(
        db=db,
        user_id=source.user_id,
        source_id=source.id,
        external_event_id=external_event_id,
        resolved_at=applied_at,
    )
    return changed_entity_uids


__all__ = ["apply_gmail_atomic_record"]
