from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.input import InputSource, SourceKind
from app.modules.runtime.apply.payload_contracts import PayloadContractError, validate_gmail_payload
from app.modules.runtime.apply.payload_extractors import (
    extract_course_parse,
    extract_link_signals,
    extract_semantic_event_draft,
    extract_source_facts_from_gmail_payload,
)
from app.modules.runtime.apply.semantic_observation_apply import apply_semantic_observation_candidate


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
    changed_entity_uids = apply_semantic_observation_candidate(
        db=db,
        source=source,
        external_event_id=external_event_id,
        source_facts=source_facts,
        semantic_draft=semantic_draft,
        course_parse=course_parse,
        link_signals=link_signals,
        raw_payload=payload,
        applied_at=applied_at,
        request_id=request_id,
        source_kind_value=SourceKind.EMAIL.value,
    )
    return changed_entity_uids


__all__ = ["apply_gmail_atomic_record"]
