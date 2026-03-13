from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import EventLinkOrigin
from app.modules.core_ingest.semantic_event_service import build_semantic_event_payload
from app.modules.core_ingest.linking_engine import (
    find_existing_entity_link,
    link_gmail_observation_to_entity,
    resolve_pending_link_candidates_for_pair,
    upsert_event_entity_link,
    upsert_link_candidate,
    with_candidate_evidence,
)
from app.modules.core_ingest.observation_store import (
    retire_active_observation_for_unresolved_transition,
    upsert_observation,
)
from app.modules.core_ingest.unresolved_store import (
    resolve_active_unresolved_records,
    upsert_active_unresolved_record,
)
from app.modules.core_ingest.payload_contracts import PayloadContractError, validate_gmail_payload
from app.modules.core_ingest.payload_extractors import (
    extract_course_parse,
    extract_link_signals,
    extract_semantic_event_draft,
    extract_source_facts_from_gmail_payload,
)
from app.modules.core_ingest.course_work_item_family_resolution import build_source_scoped_entity_uid, resolve_kind_resolution

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
            validate_gmail_payload(payload=payload, record_index=index)
        except PayloadContractError as exc:
            raise RuntimeError(str(exc)) from exc

        message_id = payload.get("message_id")
        if not isinstance(message_id, str) or not message_id.strip():
            continue
        external_event_id = message_id.strip()
        source_facts = extract_source_facts_from_gmail_payload(payload=payload)

        course_parse = extract_course_parse(payload=payload, source_facts=source_facts)
        semantic_draft = extract_semantic_event_draft(payload=payload, source_facts=source_facts)
        link_signals = extract_link_signals(
            payload=payload,
            source_facts=source_facts,
        )
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
            continue

        existing_link = find_existing_entity_link(
            db=db,
            user_id=source.user_id,
            source_id=source.id,
            external_event_id=external_event_id,
        )
        link_row = None
        should_emit_semantic_proposal = False
        if existing_link is not None and existing_link.link_origin != EventLinkOrigin.AUTO and isinstance(existing_link.entity_uid, str):
            entity_uid = existing_link.entity_uid
            should_emit_semantic_proposal = True
        else:
            link_decision = link_gmail_observation_to_entity(
                db=db,
                source=source,
                external_event_id=external_event_id,
                course_parse=course_parse,
                semantic_parse=semantic_draft,
                time_anchor_confidence=float(link_signals.get("time_anchor_confidence") or 0.0),
                signals=link_signals,
            )
            if link_decision.status == "linked" and isinstance(link_decision.entity_uid, str):
                entity_uid = link_decision.entity_uid
                link_row = upsert_event_entity_link(
                    db=db,
                    source=source,
                    external_event_id=external_event_id,
                    entity_uid=entity_uid,
                    link_origin=EventLinkOrigin.AUTO,
                    link_score=float(link_decision.score),
                    signals_json=link_signals,
                )
                should_emit_semantic_proposal = True
                resolve_pending_link_candidates_for_pair(
                    db=db,
                    user_id=source.user_id,
                    source_id=source.id,
                    external_event_id=external_event_id,
                    note="semantic_link_resolved",
                )
                if auto_link_contexts is not None:
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
                                "link_decision": {
                                    "status": link_decision.status,
                                    "reason_code": link_decision.reason_code,
                                    "score": link_decision.score,
                                },
                                "source_dtstart_utc": source_facts.get("source_dtstart_utc"),
                            },
                        }
                    )
            else:
                rule_reason = str(link_decision.score_breakdown.get("rule_reason") or "")
                candidate_can_emit_semantic_proposal = (
                    link_decision.status == "candidate"
                    and rule_reason in {"no_rule_match", "missing_raw_type"}
                    and isinstance(kind_resolution.get("family_id"), int)
                )
                entity_uid = (
                    existing_link.entity_uid
                    if existing_link is not None and isinstance(existing_link.entity_uid, str)
                    else build_source_scoped_entity_uid(source_kind=SourceKind.EMAIL.value, external_event_id=external_event_id)
                )
                should_emit_semantic_proposal = candidate_can_emit_semantic_proposal
                if link_decision.status == "candidate" and not candidate_can_emit_semantic_proposal:
                    upsert_link_candidate(
                        db=db,
                        user_id=source.user_id,
                        source_id=source.id,
                        external_event_id=external_event_id,
                        proposed_entity_uid=link_decision.candidate_entity_uid,
                        score=float(link_decision.score),
                        score_breakdown=with_candidate_evidence(score_breakdown=link_decision.score_breakdown, signals=link_signals),
                        reason_code=str(link_decision.reason_code or "score_band"),
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
        if should_emit_semantic_proposal:
            affected_entity_uids.update(changed_entity_uids)

    return affected_entity_uids


__all__ = ["apply_gmail_observations"]
