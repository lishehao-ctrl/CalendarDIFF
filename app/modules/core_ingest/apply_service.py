from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.db.models import (
    Change,
    ChangeType,
    ConnectorResultStatus,
    Event,
    EventEntity,
    EventEntityLink,
    EventLinkBlock,
    EventLinkAlertResolution,
    EventLinkCandidate,
    EventLinkCandidateReason,
    EventLinkCandidateStatus,
    EventLinkOrigin,
    IngestApplyLog,
    IngestResult,
    Input,
    InputSource,
    InputType,
    IntegrationOutbox,
    OutboxStatus,
    ReviewStatus,
    SourceEventObservation,
    SourceKind,
    SyncRequest,
    SyncRequestStatus,
)
from app.modules.core_ingest.linking_rules import LinkDecision, decide_inventory_link
from app.modules.core_ingest.merge_engine import (
    build_merge_key,
    choose_primary_observation,
    normalize_topic_signature,
)
from app.modules.core_ingest.payload_contracts import (
    PayloadContractError,
    validate_calendar_payload_v3,
    validate_gmail_payload_v3,
)
from app.modules.ingestion.ics_delta import external_event_id_from_component_key
from app.modules.review_links.alerts_service import (
    resolve_pending_link_alerts_for_entities,
    resolve_pending_link_alerts_for_pair,
    upsert_pending_link_alert,
)
from app.modules.sync.email_rules import ACTIONABLE_EVENT_TYPES
from app.modules.sync.types import CanonicalEventInput

logger = logging.getLogger(__name__)


def get_ingest_apply_status(db: Session, *, request_id: str) -> dict:
    result = db.scalar(select(IngestResult).where(IngestResult.request_id == request_id))
    apply_log = db.scalar(select(IngestApplyLog).where(IngestApplyLog.request_id == request_id))
    return {
        "request_id": request_id,
        "result_exists": result is not None,
        "result_status": result.status.value if result is not None else None,
        "applied": apply_log is not None,
        "applied_at": apply_log.applied_at if apply_log is not None else None,
    }


def apply_ingest_result_idempotent(db: Session, *, request_id: str) -> dict:
    now = datetime.now(timezone.utc)
    result = db.scalar(select(IngestResult).where(IngestResult.request_id == request_id))
    if result is None:
        raise RuntimeError("Ingest result not found")

    sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == request_id))
    source = db.get(InputSource, result.source_id)
    if source is None:
        raise RuntimeError("Input source not found for ingest result")

    try:
        db.add(
            IngestApplyLog(
                request_id=request_id,
                applied_at=now,
                status="applied",
                error_message=None,
            )
        )
        db.flush()
    except IntegrityError:
        db.rollback()
        return {
            "request_id": request_id,
            "applied": True,
            "idempotent_replay": True,
            "changes_created": 0,
        }

    try:
        changes_created = _apply_records(
            db=db,
            result=result,
            source=source,
            applied_at=now,
            request_id=request_id,
        )
        if sync_request is not None and sync_request.status != SyncRequestStatus.FAILED:
            sync_request.status = SyncRequestStatus.SUCCEEDED
            sync_request.error_code = None
            sync_request.error_message = None
        db.commit()
        return {
            "request_id": request_id,
            "applied": True,
            "idempotent_replay": False,
            "changes_created": changes_created,
        }
    except Exception:
        db.rollback()
        raise


def _apply_records(
    *,
    db: Session,
    result: IngestResult,
    source: InputSource,
    applied_at: datetime,
    request_id: str,
) -> int:
    records = result.records if isinstance(result.records, list) else []
    auto_link_contexts: list[dict] = []

    if result.status == ConnectorResultStatus.NO_CHANGE and not records:
        return 0

    canonical_input = _ensure_canonical_input_for_user(db=db, user_id=source.user_id)

    if source.source_kind == SourceKind.CALENDAR:
        affected_merge_keys = _apply_calendar_observations(
            db=db,
            source=source,
            records=records,
            applied_at=applied_at,
            request_id=request_id,
        )
    elif source.source_kind == SourceKind.EMAIL:
        affected_merge_keys = _apply_gmail_observations(
            db=db,
            source=source,
            records=records,
            applied_at=applied_at,
            request_id=request_id,
            auto_link_contexts=auto_link_contexts,
        )
    else:
        return 0

    if not affected_merge_keys:
        return 0

    db.flush()
    changes_created, pending_event_uids = _rebuild_pending_change_proposals(
        db=db,
        source=source,
        canonical_input=canonical_input,
        affected_merge_keys=affected_merge_keys,
        applied_at=applied_at,
    )
    resolve_pending_link_alerts_for_entities(
        db=db,
        user_id=source.user_id,
        entity_uids=pending_event_uids,
        resolution_code=EventLinkAlertResolution.CANONICAL_PENDING_CREATED,
        note="canonical_pending_created",
    )
    if source.source_kind == SourceKind.EMAIL and auto_link_contexts:
        _upsert_auto_link_alerts_without_pending(
            db=db,
            auto_link_contexts=auto_link_contexts,
            pending_event_uids=pending_event_uids,
        )
    return changes_created


def _ensure_canonical_input_for_user(*, db: Session, user_id: int) -> Input:
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


def _apply_calendar_observations(
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
            external_event_id = _resolve_calendar_external_event_id(payload=payload)
            if external_event_id is None:
                continue
            affected_entity_uids.update(
                _deactivate_observation(
                    db=db,
                    source_id=source.id,
                    external_event_id=external_event_id,
                    applied_at=applied_at,
                    request_id=request_id,
                )
            )
            continue

        event = _coerce_calendar_payload(payload=payload)
        resolved_external_event_id = _resolve_calendar_external_event_id(payload=payload)
        external_event_id = resolved_external_event_id or event.uid
        if resolved_external_event_id is not None:
            delta_mode = True
        if external_event_id != event.uid:
            delta_mode = True
        source_canonical = _extract_source_canonical_from_calendar_payload(
            payload=payload,
            external_event_id=external_event_id,
        )
        course_parse = _extract_enrichment_course_parse(payload=payload)
        event_parts = _extract_enrichment_event_parts(payload=payload)
        link_signals = _extract_link_signals(payload=payload, source_canonical=source_canonical)
        confidence = float(course_parse.get("confidence") or event_parts.get("confidence") or 0.0)
        event_type = _coerce_text(event_parts.get("type")) or "other"
        entity_uid = build_merge_key(
            course_label=None,
            title=None,
            start_at=None,
            end_at=None,
            event_type=None,
            source_kind=SourceKind.CALENDAR.value,
            external_event_id=external_event_id,
        )
        entity = _get_or_create_event_entity(db=db, user_id=source.user_id, entity_uid=entity_uid)
        course_label = _update_event_entity_course_profile(
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
            _upsert_observation(
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


def _resolve_calendar_external_event_id(*, payload: dict) -> str | None:
    external_event_id = payload.get("external_event_id")
    if isinstance(external_event_id, str) and external_event_id.strip():
        return external_event_id.strip()

    component_key = payload.get("component_key")
    if isinstance(component_key, str) and component_key.strip():
        return external_event_id_from_component_key(component_key.strip())
    return None


def _apply_gmail_observations(
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

        event_parts = _extract_enrichment_event_parts(payload=payload)
        event_type = _coerce_text(event_parts.get("type"))
        source_canonical = _extract_source_canonical_from_gmail_payload(payload=payload)
        due_at = _parse_optional_iso_datetime(source_canonical.get("source_dtstart_utc"))
        is_actionable_type = event_type in ACTIONABLE_EVENT_TYPES

        if not is_actionable_type:
            affected_entity_uids.update(
                _deactivate_observation(
                    db=db,
                    source_id=source.id,
                    external_event_id=external_event_id,
                    applied_at=applied_at,
                    request_id=request_id,
                )
            )
            continue

        course_parse = _extract_enrichment_course_parse(payload=payload)
        event_parts = _extract_enrichment_event_parts(payload=payload)
        link_signals = _extract_link_signals(
            payload=payload,
            source_canonical=source_canonical,
        )
        confidence = float(course_parse.get("confidence") or 0.0)
        if due_at is None:
            link_decision = _link_gmail_observation_to_entity(
                db=db,
                source=source,
                external_event_id=external_event_id,
                course_parse=course_parse,
                event_parts=event_parts,
                time_anchor_confidence=float(source_canonical.get("time_anchor_confidence") or confidence),
                signals=link_signals,
            )
            if link_decision.status == "candidate":
                _upsert_link_candidate(
                    db=db,
                    user_id=source.user_id,
                    source_id=source.id,
                    external_event_id=external_event_id,
                    proposed_entity_uid=link_decision.candidate_entity_uid,
                    score=link_decision.score,
                    score_breakdown=_with_candidate_evidence(
                        score_breakdown=link_decision.score_breakdown,
                        signals=link_signals,
                    ),
                    reason_code=link_decision.reason_code or EventLinkCandidateReason.NO_TIME_ANCHOR.value,
                )
            affected_entity_uids.update(
                _deactivate_observation(
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
        existing_link = _find_existing_entity_link(
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
            link_decision = _link_gmail_observation_to_entity(
                db=db,
                source=source,
                external_event_id=external_event_id,
                course_parse=course_parse,
                event_parts=event_parts,
                time_anchor_confidence=float(source_canonical.get("time_anchor_confidence") or confidence),
                signals=link_signals,
            )

        if link_decision.status == "linked" and link_decision.entity_uid is not None and existing_link is None:
            link_row = _upsert_event_entity_link(
                db=db,
                source=source,
                external_event_id=external_event_id,
                entity_uid=link_decision.entity_uid,
                link_origin=EventLinkOrigin.AUTO,
                link_score=link_decision.score,
                signals_json=link_signals,
            )
            _resolve_pending_link_candidates_for_pair(
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
                            "incoming_signals": _with_candidate_evidence(
                                score_breakdown={},
                                signals=link_signals,
                            ).get("incoming_signals"),
                            "source_time_anchor_confidence": source_canonical.get("time_anchor_confidence"),
                            "source_dtstart_utc": source_canonical.get("source_dtstart_utc"),
                        },
                    }
                )
        elif link_decision.status == "candidate":
            _upsert_link_candidate(
                db=db,
                user_id=source.user_id,
                source_id=source.id,
                external_event_id=external_event_id,
                proposed_entity_uid=link_decision.candidate_entity_uid,
                score=link_decision.score,
                score_breakdown=_with_candidate_evidence(
                    score_breakdown=link_decision.score_breakdown,
                    signals=link_signals,
                ),
                reason_code=link_decision.reason_code or EventLinkCandidateReason.SCORE_BAND.value,
            )
            affected_entity_uids.update(
                _deactivate_observation(
                    db=db,
                    source_id=source.id,
                    external_event_id=external_event_id,
                    applied_at=applied_at,
                    request_id=request_id,
                )
            )
            continue

        entity_uid = link_decision.entity_uid or default_entity_uid
        entity = _get_or_create_event_entity(db=db, user_id=source.user_id, entity_uid=entity_uid)
        course_label = _update_event_entity_course_profile(
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
            _upsert_observation(
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


def _extract_source_canonical_from_calendar_payload(
    *,
    payload: dict,
    external_event_id: str,
) -> dict:
    raw = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else None
    if raw is None:
        raise RuntimeError("core_ingest_payload_invalid: calendar payload missing source_canonical")
    source_title = raw.get("source_title")
    source_summary = raw.get("source_summary")
    source_dtstart = raw.get("source_dtstart_utc")
    source_dtend = raw.get("source_dtend_utc")
    if not isinstance(source_title, str) or not source_title.strip():
        raise RuntimeError("core_ingest_payload_invalid: calendar payload missing source_canonical.source_title")
    if not isinstance(source_dtstart, str) or not source_dtstart.strip():
        raise RuntimeError("core_ingest_payload_invalid: calendar payload missing source_canonical.source_dtstart_utc")
    if not isinstance(source_dtend, str) or not source_dtend.strip():
        raise RuntimeError("core_ingest_payload_invalid: calendar payload missing source_canonical.source_dtend_utc")
    return {
        "external_event_id": external_event_id,
        "component_key": raw.get("component_key") if isinstance(raw.get("component_key"), str) else payload.get("component_key"),
        "source_title": source_title.strip()[:512],
        "source_summary": source_summary[:1024] if isinstance(source_summary, str) else None,
        "source_dtstart_utc": source_dtstart.strip(),
        "source_dtend_utc": source_dtend.strip(),
        "status": raw.get("status") if isinstance(raw.get("status"), str) else None,
        "location": raw.get("location") if isinstance(raw.get("location"), str) else None,
        "organizer": raw.get("organizer") if isinstance(raw.get("organizer"), str) else None,
    }


def _extract_source_canonical_from_gmail_payload(*, payload: dict) -> dict:
    raw = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else None
    if raw is None:
        raise RuntimeError("core_ingest_payload_invalid: gmail payload missing source_canonical")
    parsed_due_at = _parse_optional_iso_datetime(raw.get("source_dtstart_utc"))
    parsed_end = _parse_optional_iso_datetime(raw.get("source_dtend_utc"))
    if parsed_due_at is not None and parsed_end is None:
        parsed_end = parsed_due_at + timedelta(hours=1)
    source_title = raw.get("source_title")
    if not isinstance(source_title, str) or not source_title.strip():
        raise RuntimeError("core_ingest_payload_invalid: gmail payload missing source_canonical.source_title")
    external_event_id = raw.get("external_event_id")
    if not isinstance(external_event_id, str) or not external_event_id.strip():
        raise RuntimeError("core_ingest_payload_invalid: gmail payload missing source_canonical.external_event_id")
    return {
        "external_event_id": external_event_id.strip(),
        "source_title": source_title.strip()[:512],
        "source_summary": raw.get("source_summary") if isinstance(raw.get("source_summary"), str) else None,
        "source_dtstart_utc": parsed_due_at.isoformat() if parsed_due_at is not None else None,
        "source_dtend_utc": parsed_end.isoformat() if parsed_end is not None else None,
        "time_anchor_confidence": float(raw.get("time_anchor_confidence"))
        if isinstance(raw.get("time_anchor_confidence"), (int, float))
        else 0.0,
        "from_header": raw.get("from_header") if isinstance(raw.get("from_header"), str) else None,
        "thread_id": raw.get("thread_id") if isinstance(raw.get("thread_id"), str) else None,
        "internal_date": raw.get("internal_date") if isinstance(raw.get("internal_date"), str) else None,
    }


def _extract_enrichment_course_parse(*, payload: dict) -> dict:
    enrichment = payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else None
    if enrichment is None:
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment")
    raw_course_parse = enrichment.get("course_parse")
    if not isinstance(raw_course_parse, dict):
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment.course_parse")
    return _normalize_course_parse(raw_course_parse)


def _extract_enrichment_event_parts(*, payload: dict) -> dict:
    enrichment = payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else None
    if enrichment is None:
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment")
    raw_event_parts = enrichment.get("event_parts")
    if not isinstance(raw_event_parts, dict):
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment.event_parts")
    return _normalize_event_parts(raw_event_parts)


def _extract_link_signals(
    *,
    payload: dict,
    source_canonical: dict,
) -> dict:
    enrichment = payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else None
    if enrichment is None:
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment")
    raw_signals = enrichment.get("link_signals")
    if not isinstance(raw_signals, dict):
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment.link_signals")
    title = _coerce_text(source_canonical.get("source_title")) or ""
    keywords = _normalize_keyword_list(raw_signals.get("keywords"))
    exam_sequence = _coerce_exam_sequence(raw_signals.get("exam_sequence"))
    location_text = _coerce_text(raw_signals.get("location_text")) or _coerce_text(source_canonical.get("location"))
    instructor_hint = _coerce_text(raw_signals.get("instructor_hint")) or _coerce_text(source_canonical.get("from_header")) or _coerce_text(source_canonical.get("organizer"))
    from_header = _coerce_text(source_canonical.get("from_header"))
    organizer = _coerce_text(source_canonical.get("organizer"))
    thread_id = _coerce_text(source_canonical.get("thread_id"))

    time_anchor_confidence = source_canonical.get("time_anchor_confidence")
    normalized_conf = float(time_anchor_confidence) if isinstance(time_anchor_confidence, (int, float)) else 0.0
    normalized_conf = max(0.0, min(1.0, normalized_conf))

    return {
        "keywords": keywords,
        "exam_sequence": exam_sequence,
        "location_text": location_text,
        "instructor_hint": instructor_hint,
        "from_header": from_header,
        "organizer": organizer,
        "thread_id": thread_id,
        "time_anchor_confidence": normalized_conf,
        "title_signature": normalize_topic_signature(title),
    }


def _normalize_keyword_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        token = item.strip().lower()
        if token not in {"exam", "midterm", "final"}:
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _coerce_exam_sequence(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _normalize_course_parse(raw: object) -> dict:
    if not isinstance(raw, dict):
        return _empty_course_parse()
    dept = raw.get("dept")
    number = raw.get("number")
    suffix = raw.get("suffix")
    quarter = raw.get("quarter")
    year2 = raw.get("year2")
    confidence = raw.get("confidence")
    evidence = raw.get("evidence")

    normalized_dept = dept.strip().upper()[:16] if isinstance(dept, str) and dept.strip() else None
    normalized_number = int(number) if isinstance(number, int) else None
    normalized_suffix = suffix.strip().upper()[:8] if isinstance(suffix, str) and suffix.strip() else None
    normalized_quarter = quarter.strip().upper() if isinstance(quarter, str) and quarter.strip() else None
    if normalized_quarter not in {"WI", "SP", "SU", "FA"}:
        normalized_quarter = None
    normalized_year2 = int(year2) if isinstance(year2, int) and 0 <= int(year2) <= 99 else None
    normalized_conf = float(confidence) if isinstance(confidence, (int, float)) else 0.0
    normalized_conf = max(0.0, min(1.0, normalized_conf))
    normalized_evidence = evidence.strip()[:80] if isinstance(evidence, str) else ""
    return {
        "dept": normalized_dept,
        "number": normalized_number,
        "suffix": normalized_suffix,
        "quarter": normalized_quarter,
        "year2": normalized_year2,
        "confidence": normalized_conf,
        "evidence": normalized_evidence,
    }


def _normalize_event_parts(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {
            "type": None,
            "index": None,
            "qualifier": None,
            "confidence": 0.0,
            "evidence": "",
        }
    type_value = raw.get("type")
    index_value = raw.get("index")
    qualifier_value = raw.get("qualifier")
    confidence_value = raw.get("confidence")
    evidence_value = raw.get("evidence")

    normalized_type = type_value.strip().lower() if isinstance(type_value, str) and type_value.strip() else None
    if normalized_type not in {"exam", "deadline", "quiz", "project", "lecture", "other"}:
        normalized_type = None
    normalized_index = int(index_value) if isinstance(index_value, int) and int(index_value) > 0 else None
    normalized_qualifier = qualifier_value.strip().lower()[:128] if isinstance(qualifier_value, str) and qualifier_value.strip() else None
    normalized_confidence = float(confidence_value) if isinstance(confidence_value, (int, float)) else 0.0
    normalized_confidence = max(0.0, min(1.0, normalized_confidence))
    normalized_evidence = evidence_value.strip()[:120] if isinstance(evidence_value, str) else ""
    return {
        "type": normalized_type,
        "index": normalized_index,
        "qualifier": normalized_qualifier,
        "confidence": normalized_confidence,
        "evidence": normalized_evidence,
    }


def _empty_course_parse() -> dict:
    return {
        "dept": None,
        "number": None,
        "suffix": None,
        "quarter": None,
        "year2": None,
        "confidence": 0.0,
        "evidence": "",
    }


def _get_or_create_event_entity(*, db: Session, user_id: int, entity_uid: str) -> EventEntity:
    row = db.scalar(
        select(EventEntity).where(
            EventEntity.user_id == user_id,
            EventEntity.entity_uid == entity_uid,
        )
    )
    if row is not None:
        return row
    row = EventEntity(
        user_id=user_id,
        entity_uid=entity_uid,
        course_best_json=None,
        course_best_strength=0,
        course_aliases_json=[],
        title_aliases_json=[],
        metadata_json={},
    )
    db.add(row)
    db.flush()
    return row


def _update_event_entity_course_profile(
    *,
    entity: EventEntity,
    source_kind: str,
    course_parse: dict,
    source_title: str | None,
) -> str:
    current_best = entity.course_best_json if isinstance(entity.course_best_json, dict) else None
    best_strength = int(entity.course_best_strength or 0)
    new_strength = _compute_course_strength(course_parse=course_parse, source_kind=source_kind, title_text=source_title)
    new_display = _course_display_name(course_parse=course_parse)

    if new_display and new_strength > best_strength:
        previous_display = _entity_best_display_name(current_best)
        if previous_display:
            entity.course_aliases_json = _append_alias(entity.course_aliases_json, previous_display, limit=24)
        entity.course_best_json = {
            "course_parse": course_parse,
            "display_name": new_display,
        }
        entity.course_best_strength = new_strength
    elif new_display:
        entity.course_aliases_json = _append_alias(entity.course_aliases_json, new_display, limit=24)

    if source_title:
        entity.title_aliases_json = _append_alias(entity.title_aliases_json, source_title, limit=24)

    best_display = _entity_best_display_name(entity.course_best_json if isinstance(entity.course_best_json, dict) else None)
    return best_display or new_display or "Unknown"


def _compute_course_strength(*, course_parse: dict, source_kind: str, title_text: str | None) -> int:
    del source_kind
    del title_text
    score = 0
    if course_parse.get("dept") is not None:
        score += 1
    if course_parse.get("number") is not None:
        score += 1
    if course_parse.get("suffix") is not None:
        score += 1
    if course_parse.get("quarter") is not None:
        score += 1
    if course_parse.get("year2") is not None:
        score += 1
    return score


def _course_display_name(*, course_parse: dict) -> str | None:
    dept = _coerce_text(course_parse.get("dept"))
    number = course_parse.get("number")
    if dept is None or not isinstance(number, int):
        return None
    suffix = _coerce_text(course_parse.get("suffix"))
    quarter = _coerce_text(course_parse.get("quarter"))
    year2 = course_parse.get("year2")
    base = f"{dept.upper()} {number}{suffix.upper() if suffix else ''}".strip()
    if quarter and isinstance(year2, int):
        return f"{base} {quarter.upper()}{year2:02d}"[:64]
    return base[:64]


def _entity_best_display_name(course_best_json: dict | None) -> str | None:
    if not isinstance(course_best_json, dict):
        return None
    value = course_best_json.get("display_name")
    return value.strip()[:64] if isinstance(value, str) and value.strip() else None


def _append_alias(raw: object, candidate: str, *, limit: int) -> list[str]:
    cleaned = candidate.strip()
    if not cleaned:
        return [item for item in raw if isinstance(item, str)] if isinstance(raw, list) else []
    out: list[str] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, str):
                continue
            normalized = item.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(normalized[:128])
            if len(out) >= limit:
                break
    key = cleaned.lower()
    if key not in seen:
        out.append(cleaned[:128])
    return out[-limit:]


def _link_gmail_observation_to_entity(
    *,
    db: Session,
    source: InputSource,
    external_event_id: str,
    course_parse: dict,
    event_parts: dict,
    time_anchor_confidence: float,
    signals: dict,
) -> LinkDecision:
    blocked_entity_uids = _blocked_entity_uid_set(
        db=db,
        user_id=source.user_id,
        source_id=source.id,
        external_event_id=external_event_id,
    )
    decision = decide_inventory_link(
        db,
        source=source,
        external_event_id=external_event_id,
        course_parse=course_parse,
        event_parts=event_parts,
        time_anchor_confidence=time_anchor_confidence,
        blocked_entity_uids=blocked_entity_uids,
    )
    breakdown = dict(decision.score_breakdown)
    breakdown["incoming_signals"] = {
        "keywords": signals.get("keywords"),
        "exam_sequence": signals.get("exam_sequence"),
        "instructor_hint": signals.get("instructor_hint"),
        "location_text": signals.get("location_text"),
        "from_header": signals.get("from_header"),
        "thread_id": signals.get("thread_id"),
    }
    return LinkDecision(
        entity_uid=decision.entity_uid,
        status=decision.status,
        score=decision.score,
        candidate_entity_uid=decision.candidate_entity_uid,
        reason_code=decision.reason_code,
        score_breakdown=breakdown,
    )


def _find_existing_entity_link(
    *,
    db: Session,
    user_id: int,
    source_id: int,
    external_event_id: str,
) -> EventEntityLink | None:
    return db.scalar(
        select(EventEntityLink).where(
            EventEntityLink.user_id == user_id,
            EventEntityLink.source_id == source_id,
            EventEntityLink.external_event_id == external_event_id,
        )
    )


def _upsert_event_entity_link(
    *,
    db: Session,
    source: InputSource,
    external_event_id: str,
    entity_uid: str,
    link_origin: EventLinkOrigin,
    link_score: float,
    signals_json: dict,
) -> EventEntityLink:
    row = _find_existing_entity_link(
        db=db,
        user_id=source.user_id,
        source_id=source.id,
        external_event_id=external_event_id,
    )
    if row is None:
        row = EventEntityLink(
            user_id=source.user_id,
            source_id=source.id,
            source_kind=source.source_kind,
            external_event_id=external_event_id,
            entity_uid=entity_uid,
            link_origin=link_origin,
            link_score=float(link_score),
            signals_json=signals_json or None,
        )
        db.add(row)
        return row

    row.source_kind = source.source_kind
    row.entity_uid = entity_uid
    row.link_origin = link_origin
    row.link_score = float(link_score)
    row.signals_json = signals_json or None
    return row


def _resolve_pending_link_candidates_for_pair(
    *,
    db: Session,
    user_id: int,
    source_id: int,
    external_event_id: str,
    note: str,
) -> None:
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(EventLinkCandidate).where(
            EventLinkCandidate.user_id == user_id,
            EventLinkCandidate.source_id == source_id,
            EventLinkCandidate.external_event_id == external_event_id,
            EventLinkCandidate.status == EventLinkCandidateStatus.PENDING,
        )
    ).all()
    for row in rows:
        row.status = EventLinkCandidateStatus.APPROVED
        row.reviewed_at = now
        row.review_note = note[:512]
        row.reviewed_by_user_id = None


def _upsert_link_candidate(
    *,
    db: Session,
    user_id: int,
    source_id: int,
    external_event_id: str,
    proposed_entity_uid: str | None,
    score: float,
    score_breakdown: dict,
    reason_code: str,
) -> EventLinkCandidate:
    resolve_pending_link_alerts_for_pair(
        db=db,
        user_id=user_id,
        source_id=source_id,
        external_event_id=external_event_id,
        resolution_code=EventLinkAlertResolution.CANDIDATE_OPENED,
        note="candidate_opened",
    )
    pending_rows = db.scalars(
        select(EventLinkCandidate).where(
            EventLinkCandidate.user_id == user_id,
            EventLinkCandidate.source_id == source_id,
            EventLinkCandidate.external_event_id == external_event_id,
            EventLinkCandidate.status == EventLinkCandidateStatus.PENDING,
        )
    ).all()
    for row in pending_rows:
        if row.proposed_entity_uid == proposed_entity_uid:
            row.score = float(score)
            row.score_breakdown_json = score_breakdown
            row.reason_code = _coerce_candidate_reason(reason_code)
            row.review_note = None
            row.reviewed_at = None
            row.reviewed_by_user_id = None
            return row

    row = EventLinkCandidate(
        user_id=user_id,
        source_id=source_id,
        external_event_id=external_event_id,
        proposed_entity_uid=proposed_entity_uid,
        score=float(score),
        score_breakdown_json=score_breakdown,
        reason_code=_coerce_candidate_reason(reason_code),
        status=EventLinkCandidateStatus.PENDING,
        reviewed_by_user_id=None,
        reviewed_at=None,
        review_note=None,
    )
    db.add(row)
    return row


def _coerce_candidate_reason(value: str) -> EventLinkCandidateReason:
    normalized = (value or "").strip().lower()
    if normalized == EventLinkCandidateReason.NO_TIME_ANCHOR.value:
        return EventLinkCandidateReason.NO_TIME_ANCHOR
    if normalized == EventLinkCandidateReason.LOW_CONFIDENCE.value:
        return EventLinkCandidateReason.LOW_CONFIDENCE
    return EventLinkCandidateReason.SCORE_BAND


def _with_candidate_evidence(*, score_breakdown: dict, signals: dict) -> dict:
    payload = dict(score_breakdown)
    payload["incoming_signals"] = {
        "keywords": signals.get("keywords"),
        "exam_sequence": signals.get("exam_sequence"),
        "instructor_hint": signals.get("instructor_hint"),
        "location_text": signals.get("location_text"),
        "from_header": signals.get("from_header"),
        "thread_id": signals.get("thread_id"),
        "title_signature": signals.get("title_signature"),
    }
    return payload


def _blocked_entity_uid_set(
    *,
    db: Session,
    user_id: int,
    source_id: int,
    external_event_id: str,
) -> set[str]:
    rows = db.scalars(
        select(EventLinkBlock).where(
            EventLinkBlock.user_id == user_id,
            EventLinkBlock.source_id == source_id,
            EventLinkBlock.external_event_id == external_event_id,
        )
    ).all()
    return {
        row.blocked_entity_uid
        for row in rows
        if isinstance(row.blocked_entity_uid, str) and row.blocked_entity_uid.strip()
    }


def _upsert_observation(
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
    normalized_payload = _normalize_observation_payload(event_payload)
    row = db.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.external_event_id == external_event_id,
        )
    )
    if row is not None:
        normalized_payload = _apply_title_degradation_guard(old_payload=row.event_payload, new_payload=normalized_payload)

    canonical_hash = _compute_payload_hash(_canonical_payload_for_hash(normalized_payload))
    full_hash = _compute_payload_hash(normalized_payload)
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
    old_canonical_payload = _canonical_payload_for_hash(old_payload)
    new_canonical_payload = _canonical_payload_for_hash(normalized_payload)
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


def _normalize_observation_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    return dict(payload)


def _canonical_payload_for_hash(payload: dict) -> dict:
    source_canonical = payload.get("source_canonical")
    if isinstance(source_canonical, dict):
        return source_canonical
    return {}


def _apply_title_degradation_guard(*, old_payload: object, new_payload: dict) -> dict:
    old = old_payload if isinstance(old_payload, dict) else {}
    old_fields = _extract_observation_title_and_times(old)
    new_fields = _extract_observation_title_and_times(new_payload)
    if old_fields is None or new_fields is None:
        return new_payload
    old_title, old_start, old_end = old_fields
    new_title, new_start, new_end = new_fields
    if old_start != new_start or old_end != new_end:
        return new_payload
    if _title_information_score(new_title) >= _title_information_score(old_title):
        return new_payload

    adjusted = dict(new_payload)
    source_canonical = adjusted.get("source_canonical") if isinstance(adjusted.get("source_canonical"), dict) else {}
    source_canonical["source_title"] = old_title
    source_canonical["source_summary"] = old_title
    adjusted["source_canonical"] = source_canonical
    enrichment = adjusted.get("enrichment") if isinstance(adjusted.get("enrichment"), dict) else {}
    enrichment["title_aliases"] = _append_alias(enrichment.get("title_aliases"), new_title, limit=24)
    adjusted["enrichment"] = enrichment
    return adjusted


def _extract_observation_title_and_times(payload: dict) -> tuple[str, str, str] | None:
    source_canonical = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}
    title = source_canonical.get("source_title")
    start = source_canonical.get("source_dtstart_utc")
    end = source_canonical.get("source_dtend_utc")
    if not isinstance(title, str) or not isinstance(start, str) or not isinstance(end, str):
        return None
    return title, start, end


def _title_information_score(value: str) -> int:
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


def _deactivate_observation(
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


def _rebuild_pending_change_proposals(
    *,
    db: Session,
    source: InputSource,
    canonical_input: Input,
    affected_merge_keys: set[str],
    applied_at: datetime,
) -> tuple[int, set[str]]:
    created_changes: list[Change] = []

    for merge_key in sorted(affected_merge_keys):
        observations = db.scalars(
            select(SourceEventObservation).where(
                SourceEventObservation.user_id == source.user_id,
                SourceEventObservation.merge_key == merge_key,
                SourceEventObservation.is_active.is_(True),
            )
        ).all()

        primary = choose_primary_observation([
            {
                "source_kind": row.source_kind.value,
                "event_payload": row.event_payload,
                "observed_at": row.observed_at,
            }
            for row in observations
        ])
        existing_event = db.scalar(
            select(Event).where(
                Event.input_id == canonical_input.id,
                Event.uid == merge_key,
            )
        )

        if primary is None and existing_event is None:
            _resolve_pending_change_as_rejected(
                db=db,
                canonical_input_id=canonical_input.id,
                event_uid=merge_key,
                applied_at=applied_at,
                note="proposal_resolved_no_active_observation",
            )
            continue

        if primary is not None:
            primary_payload = primary.get("event_payload") if isinstance(primary.get("event_payload"), dict) else {}
            candidate_after = _candidate_after_json(merge_key=merge_key, payload=primary_payload)
            if candidate_after is None:
                continue
            proposal_sources = _serialize_proposal_sources(observations)

            if existing_event is None:
                new_change = _upsert_pending_change(
                    db=db,
                    input_id=canonical_input.id,
                    event_uid=merge_key,
                    change_type=ChangeType.CREATED,
                    before_json=None,
                    after_json=candidate_after,
                    delta_seconds=None,
                    proposal_merge_key=merge_key,
                    proposal_sources_json=proposal_sources,
                    detected_at=applied_at,
                )
                if new_change is not None:
                    created_changes.append(new_change)
                continue

            before_json = _event_row_to_json(existing_event)
            if _event_json_equivalent(before_json, candidate_after):
                _resolve_pending_change_as_rejected(
                    db=db,
                    canonical_input_id=canonical_input.id,
                    event_uid=merge_key,
                    applied_at=applied_at,
                    note="proposal_already_matches_canonical",
                )
                continue

            delta_seconds = _safe_delta_seconds(before_json=before_json, after_json=candidate_after)
            new_change = _upsert_pending_change(
                db=db,
                input_id=canonical_input.id,
                event_uid=merge_key,
                change_type=ChangeType.DUE_CHANGED,
                before_json=before_json,
                after_json=candidate_after,
                delta_seconds=delta_seconds,
                proposal_merge_key=merge_key,
                proposal_sources_json=proposal_sources,
                detected_at=applied_at,
            )
            if new_change is not None:
                created_changes.append(new_change)
            continue

        assert existing_event is not None
        before_json = _event_row_to_json(existing_event)
        new_change = _upsert_pending_change(
            db=db,
            input_id=canonical_input.id,
            event_uid=merge_key,
            change_type=ChangeType.REMOVED,
            before_json=before_json,
            after_json=None,
            delta_seconds=None,
            proposal_merge_key=merge_key,
            proposal_sources_json=[],
            detected_at=applied_at,
        )
        if new_change is not None:
            created_changes.append(new_change)

    if created_changes:
        db.flush()
        _emit_review_pending_created_event(
            db=db,
            canonical_input_id=canonical_input.id,
            changes=created_changes,
            detected_at=applied_at,
        )

    pending_event_uids = set(
        db.scalars(
            select(Change.event_uid).where(
                Change.input_id == canonical_input.id,
                Change.review_status == ReviewStatus.PENDING,
                Change.event_uid.in_(sorted(affected_merge_keys)),
            )
        ).all()
    )
    return len(created_changes), pending_event_uids


def _upsert_auto_link_alerts_without_pending(
    *,
    db: Session,
    auto_link_contexts: list[dict],
    pending_event_uids: set[str],
) -> None:
    for context in auto_link_contexts:
        entity_uid = context.get("entity_uid")
        if not isinstance(entity_uid, str) or not entity_uid.strip():
            continue
        if entity_uid in pending_event_uids:
            continue
        link_row = context.get("link_row")
        link_id = int(link_row.id) if isinstance(getattr(link_row, "id", None), int) else None
        upsert_pending_link_alert(
            db=db,
            user_id=int(context["user_id"]),
            source_id=int(context["source_id"]),
            external_event_id=str(context["external_event_id"]),
            entity_uid=entity_uid,
            link_id=link_id,
            evidence_snapshot=context.get("evidence_snapshot") if isinstance(context.get("evidence_snapshot"), dict) else {},
        )


def _emit_review_pending_created_event(
    *,
    db: Session,
    canonical_input_id: int,
    changes: list[Change],
    detected_at: datetime,
) -> None:
    change_ids = [int(change.id) for change in changes if isinstance(change.id, int)]
    if not change_ids:
        return
    event = new_event(
        event_type="review.pending.created",
        aggregate_type="change_batch",
        aggregate_id=str(change_ids[0]),
        payload={
            "input_id": canonical_input_id,
            "change_ids": change_ids,
            "deliver_after": detected_at.isoformat(),
        },
    )
    db.add(
        IntegrationOutbox(
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload_json=event.payload,
            status=OutboxStatus.PENDING,
            available_at=event.available_at,
        )
    )


def _upsert_pending_change(
    *,
    db: Session,
    input_id: int,
    event_uid: str,
    change_type: ChangeType,
    before_json: dict | None,
    after_json: dict | None,
    delta_seconds: int | None,
    proposal_merge_key: str,
    proposal_sources_json: list[dict],
    detected_at: datetime,
) -> Change | None:
    existing_pending = db.scalar(
        select(Change)
        .where(
            Change.input_id == input_id,
            Change.event_uid == event_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
        .order_by(Change.id.desc())
        .limit(1)
    )

    if existing_pending is None:
        change = Change(
            input_id=input_id,
            event_uid=event_uid,
            change_type=change_type,
            detected_at=detected_at,
            before_json=before_json,
            after_json=after_json,
            delta_seconds=delta_seconds,
            viewed_at=None,
            viewed_note=None,
            review_status=ReviewStatus.PENDING,
            reviewed_at=None,
            review_note=None,
            reviewed_by_user_id=None,
            proposal_merge_key=proposal_merge_key,
            proposal_sources_json=proposal_sources_json,
            before_snapshot_id=None,
            after_snapshot_id=None,
            evidence_keys=None,
        )
        db.add(change)
        db.flush()
        return change

    if _pending_change_same(
        existing_pending,
        change_type=change_type,
        before_json=before_json,
        after_json=after_json,
        delta_seconds=delta_seconds,
        proposal_merge_key=proposal_merge_key,
        proposal_sources_json=proposal_sources_json,
    ):
        return None

    existing_pending.change_type = change_type
    existing_pending.detected_at = detected_at
    existing_pending.before_json = before_json
    existing_pending.after_json = after_json
    existing_pending.delta_seconds = delta_seconds
    existing_pending.viewed_at = None
    existing_pending.viewed_note = None
    existing_pending.review_status = ReviewStatus.PENDING
    existing_pending.reviewed_at = None
    existing_pending.review_note = None
    existing_pending.reviewed_by_user_id = None
    existing_pending.proposal_merge_key = proposal_merge_key
    existing_pending.proposal_sources_json = proposal_sources_json
    existing_pending.before_snapshot_id = None
    existing_pending.after_snapshot_id = None
    existing_pending.evidence_keys = None
    return None


def _resolve_pending_change_as_rejected(
    *,
    db: Session,
    canonical_input_id: int,
    event_uid: str,
    applied_at: datetime,
    note: str,
) -> None:
    pending = db.scalars(
        select(Change).where(
            Change.input_id == canonical_input_id,
            Change.event_uid == event_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
    ).all()
    for row in pending:
        row.review_status = ReviewStatus.REJECTED
        row.reviewed_at = applied_at
        row.review_note = note
        row.reviewed_by_user_id = None


def _pending_change_same(
    row: Change,
    *,
    change_type: ChangeType,
    before_json: dict | None,
    after_json: dict | None,
    delta_seconds: int | None,
    proposal_merge_key: str,
    proposal_sources_json: list[dict],
) -> bool:
    return (
        row.change_type == change_type
        and row.before_json == before_json
        and row.after_json == after_json
        and row.delta_seconds == delta_seconds
        and row.proposal_merge_key == proposal_merge_key
        and row.proposal_sources_json == proposal_sources_json
    )


def _serialize_proposal_sources(observations: list[SourceEventObservation]) -> list[dict]:
    rows: list[dict] = []
    for row in observations:
        payload = row.event_payload if isinstance(row.event_payload, dict) else {}
        confidence_raw = payload.get("confidence")
        confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0
        rows.append(
            {
                "source_id": row.source_id,
                "source_kind": row.source_kind.value,
                "provider": row.provider,
                "external_event_id": row.external_event_id,
                "confidence": confidence,
            }
        )
    rows.sort(
        key=lambda item: (
            float(item.get("confidence") or 0.0),
            2 if item.get("source_kind") == "calendar" else 1 if item.get("source_kind") == "email" else 0,
        ),
        reverse=True,
    )
    return rows


def _candidate_after_json(*, merge_key: str, payload: dict) -> dict | None:
    source_canonical = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}
    start_raw = source_canonical.get("source_dtstart_utc")
    end_raw = source_canonical.get("source_dtend_utc")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        return None
    start_at = _parse_iso_datetime(start_raw, field="start_at_utc", uid=merge_key)
    end_at = _parse_iso_datetime(end_raw, field="end_at_utc", uid=merge_key)
    if end_at <= start_at:
        return None

    title = source_canonical.get("source_title") if isinstance(source_canonical.get("source_title"), str) else None
    course_label = payload.get("course_label") if isinstance(payload.get("course_label"), str) else None
    if not course_label:
        course_label = _course_display_name(course_parse=_extract_enrichment_course_parse(payload=payload)) or "Unknown"
    return {
        "uid": merge_key,
        "title": (title or "Untitled")[:512],
        "course_label": (course_label or "Unknown")[:64],
        "start_at_utc": start_at.isoformat(),
        "end_at_utc": end_at.isoformat(),
    }


def _event_row_to_json(event: Event) -> dict:
    return {
        "uid": event.uid,
        "title": event.title,
        "course_label": event.course_label,
        "start_at_utc": _as_utc(event.start_at_utc).isoformat(),
        "end_at_utc": _as_utc(event.end_at_utc).isoformat(),
    }


def _event_json_equivalent(before_json: dict, after_json: dict) -> bool:
    return (
        str(before_json.get("title") or "") == str(after_json.get("title") or "")
        and str(before_json.get("start_at_utc") or "") == str(after_json.get("start_at_utc") or "")
        and str(before_json.get("end_at_utc") or "") == str(after_json.get("end_at_utc") or "")
    )


def _safe_delta_seconds(*, before_json: dict, after_json: dict) -> int | None:
    before_raw = before_json.get("start_at_utc")
    after_raw = after_json.get("start_at_utc")
    if not isinstance(before_raw, str) or not isinstance(after_raw, str):
        return None
    before = _parse_iso_datetime(before_raw, field="start_at_utc", uid="before")
    after = _parse_iso_datetime(after_raw, field="start_at_utc", uid="after")
    return int((after - before).total_seconds())


def _coerce_calendar_payload(*, payload: dict) -> CanonicalEventInput:
    source_canonical = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}
    uid_raw = source_canonical.get("external_event_id")
    uid = uid_raw.strip() if isinstance(uid_raw, str) and uid_raw.strip() else ""
    if not uid:
        raise RuntimeError("core_ingest_payload_invalid: calendar payload missing source_canonical.external_event_id")

    title_raw = source_canonical.get("source_title")
    if not isinstance(title_raw, str) or not title_raw.strip():
        raise RuntimeError(f"calendar record uid={uid} missing non-empty source_canonical.source_title")
    title = title_raw.strip()

    course_label = _course_display_name(course_parse=_extract_enrichment_course_parse(payload=payload)) or "Unknown"

    start_value = source_canonical.get("source_dtstart_utc")
    end_value = source_canonical.get("source_dtend_utc")
    start_at = _parse_iso_datetime(start_value, field="start_at", uid=uid)
    end_at = _parse_iso_datetime(end_value, field="end_at", uid=uid)
    if end_at <= start_at:
        raise RuntimeError(f"calendar record uid={uid} has end_at <= start_at")

    return CanonicalEventInput(
        uid=uid,
        course_label=course_label[:64],
        title=title[:512],
        start_at_utc=start_at,
        end_at_utc=end_at,
    )


def _parse_iso_datetime(value: object, *, field: str, uid: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"calendar record uid={uid} missing {field}")
    raw = value.strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RuntimeError(f"calendar record uid={uid} has invalid {field}: {raw}") from exc
    return _as_utc(parsed)


def _parse_optional_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return _as_utc(parsed)


def _compute_payload_hash(payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _is_unknown_course_label(value: str | None) -> bool:
    if not isinstance(value, str):
        return True
    cleaned = value.strip().lower()
    return cleaned in {"", "unknown", "n/a", "none"}


def _coerce_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
