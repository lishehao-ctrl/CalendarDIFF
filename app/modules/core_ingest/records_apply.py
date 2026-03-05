from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    EventLinkCandidateReason,
    EventLinkOrigin,
    Input,
    InputSource,
    InputType,
    SourceEventObservation,
    SourceKind,
)
from app.modules.core_ingest.canonical_coercion import coerce_calendar_payload, coerce_text, parse_optional_iso_datetime
from app.modules.core_ingest.entity_profile import get_or_create_event_entity, update_event_entity_course_profile
from app.modules.core_ingest.linking_engine import (
    LinkDecision,
    find_existing_entity_link,
    link_gmail_observation_to_entity,
    resolve_pending_link_candidates_for_pair,
    upsert_event_entity_link,
    upsert_link_candidate,
    with_candidate_evidence,
)
from app.modules.core_ingest.merge_engine import build_merge_key
from app.modules.core_ingest.observation_store import deactivate_observation, upsert_observation
from app.modules.core_ingest.payload_contracts import (
    PayloadContractError,
    validate_calendar_payload_v3,
    validate_gmail_payload_v3,
)
from app.modules.core_ingest.payload_extractors import (
    extract_enrichment_course_parse,
    extract_enrichment_event_parts,
    extract_link_signals,
    extract_source_canonical_from_calendar_payload,
    extract_source_canonical_from_gmail_payload,
)
from app.modules.ingestion.ics_delta import external_event_id_from_component_key
from app.modules.sync.email_rules import ACTIONABLE_EVENT_TYPES

logger = logging.getLogger(__name__)


def ensure_canonical_input_for_user(*, db: Session, user_id: int) -> Input:
    identity_key = f"canonical:user:{user_id}"
    input_row = db.scalar(
        select(Input).where(
            Input.user_id == user_id,
            Input.type == InputType.ICS,
            Input.identity_key == identity_key,
        )
    )
    if input_row is not None:
        return input_row

    input_row = Input(
        user_id=user_id,
        type=InputType.ICS,
        identity_key=identity_key,
        is_active=True,
    )
    db.add(input_row)
    db.flush()
    return input_row


def apply_calendar_observations(
    *,
    db: Session,
    source: InputSource,
    records: list[dict],
    applied_at: datetime,
    request_id: str,
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
                validate_calendar_payload_v3(payload=payload, record_index=index)
            except PayloadContractError as exc:
                raise RuntimeError(str(exc)) from exc

        if record_type == "calendar.event.removed":
            delta_mode = True
            external_event_id = resolve_calendar_external_event_id(payload=payload)
            if external_event_id is None:
                continue
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
        source_canonical = extract_source_canonical_from_calendar_payload(
            payload=payload,
            external_event_id=external_event_id,
        )
        course_parse = extract_enrichment_course_parse(payload=payload)
        event_parts = extract_enrichment_event_parts(payload=payload)
        link_signals = extract_link_signals(payload=payload, source_canonical=source_canonical)
        confidence = float(course_parse.get("confidence") or event_parts.get("confidence") or 0.0)
        event_type = coerce_text(event_parts.get("type")) or "other"
        entity_uid = build_merge_key(
            course_label=None,
            title=None,
            start_at=None,
            end_at=None,
            event_type=None,
            source_kind=SourceKind.CALENDAR.value,
            external_event_id=external_event_id,
        )
        entity = get_or_create_event_entity(db=db, user_id=source.user_id, entity_uid=entity_uid)
        course_label = update_event_entity_course_profile(
            entity=entity,
            source_kind=SourceKind.CALENDAR.value,
            course_parse=course_parse,
            source_title=source_canonical.get("source_title"),
        )
        logger.debug(
            "core_ingest.merge.calendar request_id=%s source_id=%s entity_uid=%s external_event_id=%s course_label=%s",
            request_id,
            source.id,
            entity_uid,
            external_event_id,
            course_label,
        )
        source_title = str(source_canonical.get("source_title") or "Untitled")
        start_iso = str(source_canonical.get("source_dtstart_utc") or event.start_at_utc.isoformat())
        end_iso = str(source_canonical.get("source_dtend_utc") or event.end_at_utc.isoformat())
        observation_payload = {
            "uid": entity_uid,
            "title": source_title,
            "course_label": course_label,
            "start_at_utc": start_iso,
            "end_at_utc": end_iso,
            "confidence": confidence,
            "raw_confidence": confidence,
            "event_type": event_type,
            "source_canonical": source_canonical,
            "enrichment": {
                "course_parse": course_parse,
                "event_parts": event_parts,
                "link_signals": link_signals,
                "payload_schema_version": "obs_v3",
            },
        }
        seen_external_ids.add(external_event_id)
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
        row.is_active = False
        row.observed_at = applied_at
        row.last_request_id = request_id
        affected_entity_uids.add(row.merge_key)

    return affected_entity_uids


def resolve_calendar_external_event_id(*, payload: dict) -> str | None:
    external_event_id = payload.get("external_event_id")
    if isinstance(external_event_id, str) and external_event_id.strip():
        return external_event_id.strip()

    component_key = payload.get("component_key")
    if isinstance(component_key, str) and component_key.strip():
        return external_event_id_from_component_key(component_key.strip())
    return None


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

        event_parts = extract_enrichment_event_parts(payload=payload)
        event_type = coerce_text(event_parts.get("type"))
        source_canonical = extract_source_canonical_from_gmail_payload(payload=payload)
        due_at = parse_optional_iso_datetime(source_canonical.get("source_dtstart_utc"))
        is_actionable_type = event_type in ACTIONABLE_EVENT_TYPES

        if not is_actionable_type:
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
        event_parts = extract_enrichment_event_parts(payload=payload)
        link_signals = extract_link_signals(
            payload=payload,
            source_canonical=source_canonical,
        )
        confidence = float(course_parse.get("confidence") or 0.0)
        if due_at is None:
            link_decision = link_gmail_observation_to_entity(
                db=db,
                source=source,
                external_event_id=external_event_id,
                course_parse=course_parse,
                event_parts=event_parts,
                time_anchor_confidence=float(source_canonical.get("time_anchor_confidence") or confidence),
                signals=link_signals,
            )
            if link_decision.status == "candidate":
                upsert_link_candidate(
                    db=db,
                    user_id=source.user_id,
                    source_id=source.id,
                    external_event_id=external_event_id,
                    proposed_entity_uid=link_decision.candidate_entity_uid,
                    score=link_decision.score,
                    score_breakdown=with_candidate_evidence(
                        score_breakdown=link_decision.score_breakdown,
                        signals=link_signals,
                    ),
                    reason_code=link_decision.reason_code or EventLinkCandidateReason.NO_TIME_ANCHOR.value,
                )
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
        default_entity_uid = build_merge_key(
            course_label=None,
            title=None,
            start_at=None,
            end_at=None,
            event_type=None,
            source_kind=SourceKind.EMAIL.value,
            external_event_id=external_event_id,
        )
        existing_link = find_existing_entity_link(
            db=db,
            user_id=source.user_id,
            source_id=source.id,
            external_event_id=external_event_id,
        )
        if existing_link is not None:
            link_decision = LinkDecision(
                entity_uid=existing_link.entity_uid,
                status="linked",
                score=float(existing_link.link_score or 1.0),
                candidate_entity_uid=existing_link.entity_uid,
                reason_code="existing_link",
                score_breakdown={"existing_link": 1.0},
            )
        else:
            link_decision = link_gmail_observation_to_entity(
                db=db,
                source=source,
                external_event_id=external_event_id,
                course_parse=course_parse,
                event_parts=event_parts,
                time_anchor_confidence=float(source_canonical.get("time_anchor_confidence") or confidence),
                signals=link_signals,
            )

        if link_decision.status == "linked" and link_decision.entity_uid is not None and existing_link is None:
            link_row = upsert_event_entity_link(
                db=db,
                source=source,
                external_event_id=external_event_id,
                entity_uid=link_decision.entity_uid,
                link_origin=EventLinkOrigin.AUTO,
                link_score=link_decision.score,
                signals_json=link_signals,
            )
            resolve_pending_link_candidates_for_pair(
                db=db,
                user_id=source.user_id,
                source_id=source.id,
                external_event_id=external_event_id,
                note="auto_link_resolved",
            )
            if auto_link_contexts is not None:
                auto_link_contexts.append(
                    {
                        "user_id": source.user_id,
                        "source_id": source.id,
                        "external_event_id": external_event_id,
                        "entity_uid": link_decision.entity_uid,
                        "link_row": link_row,
                        "evidence_snapshot": {
                            "request_id": request_id,
                            "source_id": source.id,
                            "external_event_id": external_event_id,
                            "entity_uid": link_decision.entity_uid,
                            "link_reason_code": link_decision.reason_code,
                            "rule_evidence": link_decision.score_breakdown,
                            "incoming_signals": with_candidate_evidence(
                                score_breakdown={},
                                signals=link_signals,
                            ).get("incoming_signals"),
                            "source_time_anchor_confidence": source_canonical.get("time_anchor_confidence"),
                            "source_dtstart_utc": source_canonical.get("source_dtstart_utc"),
                        },
                    }
                )
        elif link_decision.status == "candidate":
            upsert_link_candidate(
                db=db,
                user_id=source.user_id,
                source_id=source.id,
                external_event_id=external_event_id,
                proposed_entity_uid=link_decision.candidate_entity_uid,
                score=link_decision.score,
                score_breakdown=with_candidate_evidence(
                    score_breakdown=link_decision.score_breakdown,
                    signals=link_signals,
                ),
                reason_code=link_decision.reason_code or EventLinkCandidateReason.SCORE_BAND.value,
            )
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

        entity_uid = link_decision.entity_uid or default_entity_uid
        entity = get_or_create_event_entity(db=db, user_id=source.user_id, entity_uid=entity_uid)
        course_label = update_event_entity_course_profile(
            entity=entity,
            source_kind=SourceKind.EMAIL.value,
            course_parse=course_parse,
            source_title=source_canonical.get("source_title"),
        )
        enrichment = {
            "course_parse": course_parse,
            "link_signals": link_signals,
            "link": {
                "status": link_decision.status,
                "score": round(float(link_decision.score), 4),
                "candidate_entity_uid": link_decision.candidate_entity_uid,
                "reason_code": link_decision.reason_code,
                "score_breakdown": link_decision.score_breakdown,
            },
        }
        logger.debug(
            "core_ingest.merge.gmail request_id=%s source_id=%s entity_uid=%s external_event_id=%s link_status=%s link_score=%.3f",
            request_id,
            source.id,
            entity_uid,
            external_event_id,
            link_decision.status,
            float(link_decision.score),
        )

        observation_payload = {
            "uid": entity_uid,
            "title": str(source_canonical.get("source_title") or f"Email event {external_event_id}")[:512],
            "course_label": course_label,
            "start_at_utc": str(source_canonical.get("source_dtstart_utc") or due_at.isoformat()),
            "end_at_utc": str(source_canonical.get("source_dtend_utc") or (due_at + timedelta(hours=1)).isoformat()),
            "confidence": confidence,
            "raw_confidence": confidence,
            "event_type": event_type,
            "message_id": external_event_id,
            "source_canonical": source_canonical,
            "enrichment": enrichment,
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

__all__ = [
    "apply_calendar_observations",
    "apply_gmail_observations",
    "ensure_canonical_input_for_user",
    "resolve_calendar_external_event_id",
]
