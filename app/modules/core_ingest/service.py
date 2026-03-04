from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.db.models import (
    Change,
    ChangeType,
    ConnectorResultStatus,
    EmailActionItem,
    EmailMessage,
    EmailRoute,
    EmailRuleAnalysis,
    EmailRuleLabel,
    Event,
    EventEntity,
    EventEntityLink,
    EventLinkBlock,
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
    User,
)
from app.modules.core_ingest.merge_engine import (
    build_merge_key,
    choose_primary_observation,
    normalize_topic_signature,
)
from app.modules.ingestion.ics_delta import external_event_id_from_component_key
from app.modules.sync.email_rules import ACTIONABLE_EVENT_TYPES
from app.modules.sync.types import CanonicalEventInput

GMAIL_EVENT_TYPES = ACTIONABLE_EVENT_TYPES | {"announcement", "grade", "other"}
EMAIL_EVENT_KEYS = sorted(ACTIONABLE_EVENT_TYPES | {"announcement", "grade", "other"})
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _LinkDecision:
    entity_uid: str | None
    status: str
    score: float
    candidate_entity_uid: str | None
    reason_code: str | None
    score_breakdown: dict


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
        _upsert_gmail_audit_tables(
            db=db,
            source=source,
            records=records,
            applied_at=applied_at,
        )
        affected_merge_keys = _apply_gmail_observations(
            db=db,
            source=source,
            records=records,
            applied_at=applied_at,
            request_id=request_id,
        )
    else:
        return 0

    if not affected_merge_keys:
        return 0

    db.flush()
    return _rebuild_pending_change_proposals(
        db=db,
        source=source,
        canonical_input=canonical_input,
        affected_merge_keys=affected_merge_keys,
        applied_at=applied_at,
    )


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

        event = _coerce_calendar_payload(payload=payload, source_id=source.id, fallback_index=index)
        resolved_external_event_id = _resolve_calendar_external_event_id(payload=payload)
        external_event_id = resolved_external_event_id or event.uid
        if resolved_external_event_id is not None:
            delta_mode = True
        if external_event_id != event.uid:
            delta_mode = True
        source_canonical = _extract_source_canonical_from_calendar_payload(
            payload=payload,
            fallback_title=event.title,
            fallback_start=event.start_at_utc,
            fallback_end=event.end_at_utc,
            external_event_id=external_event_id,
        )
        course_parse = _extract_enrichment_course_parse(payload=payload)
        confidence = float(course_parse.get("confidence") or 0.0)
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
            "event_type": "event",
            "source_canonical": source_canonical,
            "enrichment": {
                "course_parse": course_parse,
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
) -> set[str]:
    affected_entity_uids: set[str] = set()
    timezone_name = _resolve_user_timezone_name(db=db, user_id=source.user_id)

    for index, record in enumerate(records):
        if not isinstance(record, dict) or record.get("record_type") != "gmail.message.extracted":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue

        message_id = payload.get("message_id")
        if not isinstance(message_id, str) or not message_id.strip():
            continue
        external_event_id = message_id.strip()

        event_type_raw = payload.get("event_type")
        event_type = event_type_raw.strip().lower() if isinstance(event_type_raw, str) and event_type_raw.strip() else None
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
        link_signals = _extract_link_signals(
            payload=payload,
            source_canonical=source_canonical,
            fallback_title=str(source_canonical.get("source_title") or ""),
        )
        confidence_raw = payload.get("confidence")
        confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else float(course_parse.get("confidence") or 0.0)
        if due_at is None:
            link_decision = _link_gmail_observation_to_entity(
                db=db,
                source=source,
                external_event_id=external_event_id,
                due_at=None,
                timezone_name=timezone_name,
                course_parse=course_parse,
                confidence=confidence,
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
            link_decision = _LinkDecision(
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
                due_at=due_at,
                timezone_name=timezone_name,
                course_parse=course_parse,
                confidence=confidence,
                signals=link_signals,
            )

        if link_decision.status == "linked" and link_decision.entity_uid is not None and existing_link is None:
            _upsert_event_entity_link(
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
    fallback_title: str,
    fallback_start: datetime,
    fallback_end: datetime,
    external_event_id: str,
) -> dict:
    raw = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}
    source_title = raw.get("source_title") if isinstance(raw.get("source_title"), str) else fallback_title
    source_summary = raw.get("source_summary") if isinstance(raw.get("source_summary"), str) else source_title
    source_dtstart = raw.get("source_dtstart_utc") if isinstance(raw.get("source_dtstart_utc"), str) else fallback_start.isoformat()
    source_dtend = raw.get("source_dtend_utc") if isinstance(raw.get("source_dtend_utc"), str) else fallback_end.isoformat()
    return {
        "external_event_id": external_event_id,
        "component_key": raw.get("component_key") if isinstance(raw.get("component_key"), str) else payload.get("component_key"),
        "source_title": source_title[:512],
        "source_summary": source_summary[:1024] if isinstance(source_summary, str) else None,
        "source_dtstart_utc": source_dtstart,
        "source_dtend_utc": source_dtend,
        "status": raw.get("status") if isinstance(raw.get("status"), str) else None,
        "location": raw.get("location") if isinstance(raw.get("location"), str) else None,
        "organizer": raw.get("organizer") if isinstance(raw.get("organizer"), str) else None,
    }


def _extract_source_canonical_from_gmail_payload(*, payload: dict) -> dict:
    raw = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}
    message_id = payload.get("message_id") if isinstance(payload.get("message_id"), str) else None
    subject = payload.get("subject") if isinstance(payload.get("subject"), str) else None
    snippet = payload.get("snippet") if isinstance(payload.get("snippet"), str) else None
    from_header = payload.get("from_header") if isinstance(payload.get("from_header"), str) else None
    thread_id = payload.get("thread_id") if isinstance(payload.get("thread_id"), str) else None
    internal_date = payload.get("internal_date") if isinstance(payload.get("internal_date"), str) else None
    due_at = payload.get("due_at") if isinstance(payload.get("due_at"), str) else None
    parsed_due_at = _parse_optional_iso_datetime(due_at or raw.get("source_dtstart_utc"))
    parsed_end = _parse_optional_iso_datetime(raw.get("source_dtend_utc"))
    if parsed_due_at is not None and parsed_end is None:
        parsed_end = parsed_due_at + timedelta(hours=1)
    return {
        "external_event_id": message_id,
        "source_title": (raw.get("source_title") if isinstance(raw.get("source_title"), str) else subject or "Untitled")[:512],
        "source_summary": raw.get("source_summary") if isinstance(raw.get("source_summary"), str) else snippet,
        "source_dtstart_utc": parsed_due_at.isoformat() if parsed_due_at is not None else None,
        "source_dtend_utc": parsed_end.isoformat() if parsed_end is not None else None,
        "time_anchor_confidence": float(raw.get("time_anchor_confidence"))
        if isinstance(raw.get("time_anchor_confidence"), (int, float))
        else float(payload.get("confidence"))
        if isinstance(payload.get("confidence"), (int, float))
        else 0.0,
        "from_header": raw.get("from_header") if isinstance(raw.get("from_header"), str) else from_header,
        "thread_id": raw.get("thread_id") if isinstance(raw.get("thread_id"), str) else thread_id,
        "internal_date": raw.get("internal_date") if isinstance(raw.get("internal_date"), str) else internal_date,
    }


def _extract_enrichment_course_parse(*, payload: dict) -> dict:
    enrichment = payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else {}
    raw_course_parse = enrichment.get("course_parse")
    if raw_course_parse is None and isinstance(payload.get("course_parse"), dict):
        raw_course_parse = payload.get("course_parse")
    return _normalize_course_parse(raw_course_parse)


def _extract_link_signals(
    *,
    payload: dict,
    source_canonical: dict,
    fallback_title: str,
) -> dict:
    enrichment = payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else {}
    raw_signals = enrichment.get("link_signals") if isinstance(enrichment.get("link_signals"), dict) else {}

    source_summary = _coerce_text(source_canonical.get("source_summary")) or _coerce_text(payload.get("snippet"))
    title = _coerce_text(source_canonical.get("source_title")) or _coerce_text(fallback_title) or ""
    combined_text = " ".join(item for item in [title, source_summary] if item).strip()

    keywords = _normalize_keyword_list(raw_signals.get("keywords"))
    if not keywords:
        keywords = _keywords_from_text(combined_text)

    exam_sequence = _coerce_exam_sequence(raw_signals.get("exam_sequence"))
    if exam_sequence is None:
        exam_sequence = _extract_exam_sequence(combined_text)

    location_text = (
        _coerce_text(raw_signals.get("location_text"))
        or _coerce_text(source_canonical.get("location"))
        or _coerce_text(payload.get("location_text"))
        or _coerce_text((payload.get("raw_extract") or {}).get("location_text") if isinstance(payload.get("raw_extract"), dict) else None)
    )
    instructor_hint = _coerce_text(raw_signals.get("instructor_hint")) or _coerce_text(source_canonical.get("from_header")) or _coerce_text(payload.get("from_header"))
    from_header = _coerce_text(source_canonical.get("from_header")) or _coerce_text(payload.get("from_header"))
    organizer = _coerce_text(source_canonical.get("organizer"))
    thread_id = _coerce_text(source_canonical.get("thread_id")) or _coerce_text(payload.get("thread_id"))

    time_anchor_confidence = source_canonical.get("time_anchor_confidence")
    if not isinstance(time_anchor_confidence, (int, float)):
        time_anchor_confidence = payload.get("confidence")
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


def _keywords_from_text(text: str) -> list[str]:
    lowered = (text or "").lower()
    out: list[str] = []
    for token in ("exam", "midterm", "final"):
        if token in lowered:
            out.append(token)
    return out


def _coerce_exam_sequence(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _extract_exam_sequence(text: str) -> int | None:
    match = re.search(r"\\bexam\\s*([0-9]+)\\b", text, flags=re.I)
    if match is None:
        return None
    try:
        value = int(match.group(1))
    except Exception:
        return None
    return value if value > 0 else None


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
    due_at: datetime | None,
    timezone_name: str,
    course_parse: dict,
    confidence: float,
    signals: dict,
) -> _LinkDecision:
    if due_at is None:
        return _LinkDecision(
            entity_uid=None,
            status="candidate",
            score=0.0,
            candidate_entity_uid=None,
            reason_code=EventLinkCandidateReason.NO_TIME_ANCHOR.value,
            score_breakdown={"reason": EventLinkCandidateReason.NO_TIME_ANCHOR.value},
        )
    time_anchor_confidence = float(signals.get("time_anchor_confidence")) if isinstance(signals.get("time_anchor_confidence"), (int, float)) else float(confidence)
    if time_anchor_confidence < 0.5:
        return _LinkDecision(
            entity_uid=None,
            status="candidate",
            score=0.0,
            candidate_entity_uid=None,
            reason_code=EventLinkCandidateReason.LOW_CONFIDENCE.value,
            score_breakdown={
                "reason": EventLinkCandidateReason.LOW_CONFIDENCE.value,
                "time_anchor_confidence": round(float(time_anchor_confidence), 4),
            },
        )

    candidates = db.scalars(
        select(SourceEventObservation).where(
            SourceEventObservation.user_id == source.user_id,
            SourceEventObservation.source_kind == SourceKind.CALENDAR,
            SourceEventObservation.is_active.is_(True),
        )
    ).all()
    if not candidates:
        return _LinkDecision(
            entity_uid=None,
            status="unlinked",
            score=0.0,
            candidate_entity_uid=None,
            reason_code="no_candidates",
            score_breakdown={"reason": "no_candidates"},
        )

    blocked_entity_uids = _blocked_entity_uid_set(
        db=db,
        user_id=source.user_id,
        source_id=source.id,
        external_event_id=external_event_id,
    )
    variant_suffix_index = _build_variant_suffix_index(candidates)

    incoming_dept = _coerce_text(course_parse.get("dept"))
    incoming_number = course_parse.get("number") if isinstance(course_parse.get("number"), int) else None
    incoming_suffix = _coerce_text(course_parse.get("suffix"))
    incoming_has_anchor = incoming_dept is not None and isinstance(incoming_number, int)
    incoming_variant_key = (incoming_dept, int(incoming_number)) if incoming_has_anchor else None
    variant_suffixes = (
        variant_suffix_index.get(incoming_variant_key, set()) if incoming_variant_key is not None else set()
    )
    variant_ambiguous = len(variant_suffixes) >= 2

    best_uid: str | None = None
    best_score = 0.0
    best_breakdown: dict = {"reason": "no_candidate_in_window"}
    best_candidate_suffix: str | None = None
    best_exact_suffix_uid: str | None = None
    best_exact_suffix_score = 0.0
    best_exact_suffix_breakdown: dict = {"reason": "no_exact_suffix_candidate"}
    blocked_hit = False
    for row in candidates:
        payload = row.event_payload if isinstance(row.event_payload, dict) else {}
        source_canonical = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}
        candidate_start = _parse_optional_iso_datetime(source_canonical.get("source_dtstart_utc") or payload.get("start_at_utc"))
        if candidate_start is None:
            continue
        if not _same_local_day(due_at, candidate_start, timezone_name=timezone_name):
            continue
        delta_minutes = abs((candidate_start - due_at).total_seconds()) / 60.0
        if delta_minutes > 30:
            continue

        candidate_parse = _extract_enrichment_course_parse(payload=payload)
        candidate_signals = _extract_link_signals(
            payload=payload,
            source_canonical=source_canonical,
            fallback_title=str(source_canonical.get("source_title") or payload.get("title") or ""),
        )
        score_breakdown = _score_link_candidate(
            delta_minutes=delta_minutes,
            incoming_parse=course_parse,
            candidate_parse=candidate_parse,
            incoming_signals=signals,
            candidate_signals=candidate_signals,
        )
        score = float(score_breakdown.get("total") or 0.0)
        if row.merge_key in blocked_entity_uids:
            blocked_hit = True
            continue

        candidate_suffix = _coerce_text(candidate_parse.get("suffix"))
        if score > best_score:
            best_score = score
            best_uid = row.merge_key
            best_breakdown = score_breakdown
            best_candidate_suffix = candidate_suffix

        if variant_ambiguous and incoming_suffix and candidate_suffix == incoming_suffix and score > best_exact_suffix_score:
            best_exact_suffix_score = score
            best_exact_suffix_uid = row.merge_key
            best_exact_suffix_breakdown = score_breakdown

    if best_uid is None:
        reason = "blocked" if blocked_hit else "no_candidate_in_window"
        return _LinkDecision(
            entity_uid=None,
            status="unlinked",
            score=0.0,
            candidate_entity_uid=None,
            reason_code=reason,
            score_breakdown={"reason": reason},
        )

    if not incoming_has_anchor:
        breakdown = dict(best_breakdown)
        breakdown["missing_dept_or_number"] = True
        breakdown["variant_ambiguous"] = variant_ambiguous
        if variant_suffixes:
            breakdown["variant_suffixes"] = sorted(variant_suffixes)
        return _LinkDecision(
            entity_uid=None,
            status="candidate",
            score=best_score,
            candidate_entity_uid=best_uid,
            reason_code=EventLinkCandidateReason.SCORE_BAND.value,
            score_breakdown=breakdown,
        )

    if variant_ambiguous:
        if not incoming_suffix:
            breakdown = dict(best_breakdown)
            breakdown["variant_ambiguous"] = True
            breakdown["incoming_suffix_missing"] = True
            breakdown["suffix_exact_required"] = True
            breakdown["variant_suffixes"] = sorted(variant_suffixes)
            return _LinkDecision(
                entity_uid=None,
                status="candidate",
                score=best_score,
                candidate_entity_uid=best_uid,
                reason_code=EventLinkCandidateReason.SCORE_BAND.value,
                score_breakdown=breakdown,
            )

        if best_exact_suffix_uid is None:
            breakdown = dict(best_breakdown)
            breakdown["variant_ambiguous"] = True
            breakdown["suffix_exact_required"] = True
            breakdown["suffix_mismatch"] = True
            breakdown["incoming_suffix"] = incoming_suffix
            breakdown["candidate_suffix"] = best_candidate_suffix
            breakdown["variant_suffixes"] = sorted(variant_suffixes)
            return _LinkDecision(
                entity_uid=None,
                status="candidate",
                score=best_score,
                candidate_entity_uid=best_uid,
                reason_code=EventLinkCandidateReason.SCORE_BAND.value,
                score_breakdown=breakdown,
            )

        breakdown = dict(best_exact_suffix_breakdown)
        breakdown["variant_ambiguous"] = True
        breakdown["suffix_exact_required"] = True
        breakdown["incoming_suffix"] = incoming_suffix
        breakdown["candidate_suffix"] = incoming_suffix
        breakdown["variant_suffixes"] = sorted(variant_suffixes)
        return _LinkDecision(
            entity_uid=best_exact_suffix_uid,
            status="linked",
            score=best_exact_suffix_score,
            candidate_entity_uid=best_exact_suffix_uid,
            reason_code="auto_link_variant_suffix_exact",
            score_breakdown=breakdown,
        )

    breakdown = dict(best_breakdown)
    breakdown["variant_ambiguous"] = False
    return _LinkDecision(
        entity_uid=best_uid,
        status="linked",
        score=best_score,
        candidate_entity_uid=best_uid,
        reason_code="auto_link_anchor_present",
        score_breakdown=breakdown,
    )


def _resolve_user_timezone_name(*, db: Session, user_id: int) -> str:
    row = db.get(User, user_id)
    timezone_name = row.timezone_name if row is not None else None
    if isinstance(timezone_name, str) and timezone_name.strip():
        return timezone_name.strip()
    return "UTC"


def _same_local_day(left: datetime, right: datetime, *, timezone_name: str) -> bool:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = timezone.utc
    return left.astimezone(tz).date() == right.astimezone(tz).date()


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


def _build_variant_suffix_index(observations: list[SourceEventObservation]) -> dict[tuple[str, int], set[str]]:
    index: dict[tuple[str, int], set[str]] = {}
    for row in observations:
        payload = row.event_payload if isinstance(row.event_payload, dict) else {}
        course_parse = _extract_enrichment_course_parse(payload=payload)
        dept = _coerce_text(course_parse.get("dept"))
        number = course_parse.get("number")
        suffix = _coerce_text(course_parse.get("suffix"))
        if dept is None or not isinstance(number, int) or suffix is None:
            continue
        key = (dept, int(number))
        bucket = index.get(key)
        if bucket is None:
            bucket = set()
            index[key] = bucket
        bucket.add(suffix)
    return index


def _score_link_candidate(
    *,
    delta_minutes: float,
    incoming_parse: dict,
    candidate_parse: dict,
    incoming_signals: dict,
    candidate_signals: dict,
) -> dict:
    time_score = _time_score(delta_minutes)
    if time_score <= 0:
        return {
            "time_score": 0.0,
            "course_score": 0.0,
            "keyword_score": 0.0,
            "exam_sequence_score": 0.0,
            "instructor_score": 0.0,
            "location_score": 0.0,
            "title_score": 0.0,
            "course_match": "none",
            "prefix_constraint_passed": False,
            "delta_minutes": round(delta_minutes, 3),
            "total": 0.0,
        }

    keyword_score = _keyword_overlap_score(
        incoming_keywords=_normalize_keyword_set(incoming_signals.get("keywords")),
        candidate_keywords=_normalize_keyword_set(candidate_signals.get("keywords")),
    )
    exam_sequence_score = _exam_sequence_score(
        incoming_sequence=incoming_signals.get("exam_sequence"),
        candidate_sequence=candidate_signals.get("exam_sequence"),
    )
    instructor_score = _instructor_signal_score(
        incoming=_pick_instructor_signal(incoming_signals),
        candidate=_pick_instructor_signal(candidate_signals),
    )
    location_score = _location_signal_score(
        incoming_text=_coerce_text(incoming_signals.get("location_text")),
        candidate_text=_coerce_text(candidate_signals.get("location_text")),
    )

    extra_evidence = keyword_score > 0 or instructor_score > 0 or location_score > 0
    exact_match = _course_parse_exact_match(a=incoming_parse, b=candidate_parse)
    prefix_match = _course_parse_prefix_match(a=incoming_parse, b=candidate_parse)
    prefix_constraint_passed = False
    course_score = 0.0
    course_match = "none"
    if exact_match:
        course_score = 0.25
        course_match = "exact"
    elif prefix_match:
        course_match = "prefix"
        if delta_minutes <= 15 and extra_evidence:
            prefix_constraint_passed = True
            course_score = 0.12
        else:
            prefix_constraint_passed = False

    title_score = 0.0
    if exact_match:
        incoming_signature = _coerce_text(incoming_signals.get("title_signature"))
        candidate_signature = _coerce_text(candidate_signals.get("title_signature"))
        if incoming_signature and candidate_signature and incoming_signature == candidate_signature:
            title_score = 0.15

    total = time_score + course_score + keyword_score + exam_sequence_score + instructor_score + location_score + title_score
    return {
        "time_score": round(time_score, 4),
        "course_score": round(course_score, 4),
        "keyword_score": round(keyword_score, 4),
        "exam_sequence_score": round(exam_sequence_score, 4),
        "instructor_score": round(instructor_score, 4),
        "location_score": round(location_score, 4),
        "title_score": round(title_score, 4),
        "course_match": course_match,
        "prefix_constraint_passed": prefix_constraint_passed,
        "delta_minutes": round(delta_minutes, 3),
        "total": round(total, 4),
    }


def _time_score(delta_minutes: float) -> float:
    if delta_minutes <= 5:
        return 0.5
    if delta_minutes <= 15:
        return 0.35
    if delta_minutes <= 30:
        return 0.2
    return 0.0


def _normalize_keyword_set(raw: object) -> set[str]:
    if not isinstance(raw, list):
        return set()
    allowed = {"exam", "midterm", "final"}
    out: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        normalized = item.strip().lower()
        if normalized in allowed:
            out.add(normalized)
    return out


def _keyword_overlap_score(*, incoming_keywords: set[str], candidate_keywords: set[str]) -> float:
    if not incoming_keywords or not candidate_keywords:
        return 0.0
    return 0.1 if incoming_keywords.intersection(candidate_keywords) else 0.0


def _exam_sequence_score(*, incoming_sequence: object, candidate_sequence: object) -> float:
    if not isinstance(incoming_sequence, int) or not isinstance(candidate_sequence, int):
        return 0.0
    return 0.05 if incoming_sequence == candidate_sequence else 0.0


def _pick_instructor_signal(signals: dict) -> str | None:
    return _coerce_text(signals.get("instructor_hint")) or _coerce_text(signals.get("from_header")) or _coerce_text(signals.get("organizer"))


def _normalize_person_token(value: str | None) -> str | None:
    if value is None:
        return None
    lowered = value.lower()
    email_match = re.search(r"([a-z0-9._%+-]+@[a-z0-9.-]+)", lowered)
    if email_match:
        email = email_match.group(1)
        local = email.split("@", 1)[0]
        return local.strip() or email.strip()
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
    if not cleaned:
        return None
    tokens = cleaned.split()
    return " ".join(tokens[:3])


def _instructor_signal_score(*, incoming: str | None, candidate: str | None) -> float:
    left = _normalize_person_token(incoming)
    right = _normalize_person_token(candidate)
    if not left or not right:
        return 0.0
    if left == right or left in right or right in left:
        return 0.15
    return 0.0


def _tokenize_location(value: str | None) -> set[str]:
    if value is None:
        return set()
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    if not normalized:
        return set()
    return {token for token in normalized.split() if len(token) > 1}


def _location_signal_score(*, incoming_text: str | None, candidate_text: str | None) -> float:
    left = _tokenize_location(incoming_text)
    right = _tokenize_location(candidate_text)
    if not left or not right:
        return 0.0
    return 0.1 if left.intersection(right) else 0.0


def _course_parse_exact_match(*, a: dict, b: dict) -> bool:
    if not (
        _coerce_text(a.get("dept")) == _coerce_text(b.get("dept"))
        and isinstance(a.get("number"), int)
        and isinstance(b.get("number"), int)
        and int(a.get("number")) == int(b.get("number"))
    ):
        return False
    suffix_a = _coerce_text(a.get("suffix"))
    suffix_b = _coerce_text(b.get("suffix"))
    return suffix_a == suffix_b


def _course_parse_prefix_match(*, a: dict, b: dict) -> bool:
    if not (
        _coerce_text(a.get("dept")) == _coerce_text(b.get("dept"))
        and isinstance(a.get("number"), int)
        and isinstance(b.get("number"), int)
        and int(a.get("number")) == int(b.get("number"))
    ):
        return False
    suffix_a = _coerce_text(a.get("suffix"))
    suffix_b = _coerce_text(b.get("suffix"))
    if suffix_a is None or suffix_b is None:
        return suffix_a != suffix_b
    return suffix_a != suffix_b and (suffix_a.startswith(suffix_b) or suffix_b.startswith(suffix_a))


def _has_prefix_extra_evidence(*, title: str, event_type: str | None) -> bool:
    lowered = title.lower()
    if event_type == "exam":
        return True
    return any(token in lowered for token in ("exam", "midterm", "final"))


def _upsert_gmail_audit_tables(
    *,
    db: Session,
    source: InputSource,
    records: list[dict],
    applied_at: datetime,
) -> None:
    latest_by_email: dict[str, dict] = {}
    for record in records:
        if not isinstance(record, dict) or record.get("record_type") != "gmail.message.extracted":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        message_id = payload.get("message_id")
        if not isinstance(message_id, str) or not message_id.strip():
            continue
        latest_by_email[message_id.strip()] = payload

    for message_id, payload in latest_by_email.items():
        event_type_raw = payload.get("event_type")
        event_type = event_type_raw.strip().lower() if isinstance(event_type_raw, str) and event_type_raw.strip() else None
        if event_type not in GMAIL_EVENT_TYPES:
            event_type = None

        confidence_raw = payload.get("confidence")
        confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.5
        confidence = max(0.0, min(1.0, confidence))

        subject_raw = payload.get("subject")
        subject = subject_raw.strip()[:512] if isinstance(subject_raw, str) and subject_raw.strip() else None
        due_at_raw = payload.get("due_at")
        due_at = due_at_raw.strip() if isinstance(due_at_raw, str) and due_at_raw.strip() else None

        raw_extract = payload.get("raw_extract") if isinstance(payload.get("raw_extract"), dict) else {}

        email_row = db.get(EmailMessage, message_id)
        evidence_key = {"kind": "gmail", "message_id": message_id}
        if email_row is None:
            email_row = EmailMessage(
                email_id=message_id,
                user_id=source.user_id,
                from_addr=None,
                subject=subject,
                date_rfc822=None,
                received_at=applied_at,
                evidence_key=evidence_key,
            )
            db.add(email_row)
        else:
            email_row.user_id = source.user_id
            email_row.subject = subject
            email_row.evidence_key = evidence_key

        label_row = db.get(EmailRuleLabel, message_id)
        if label_row is None:
            label_row = EmailRuleLabel(email_id=message_id)
            db.add(label_row)
        label_row.label = "KEEP" if event_type in ACTIONABLE_EVENT_TYPES else "DROP"
        label_row.confidence = confidence
        label_row.reasons = ["v2_llm_ingest"]
        label_row.course_hints = _extract_course_hints(raw_extract)
        label_row.event_type = event_type
        label_row.raw_extract = {
            "deadline_text": _coerce_text(raw_extract.get("deadline_text")) or due_at,
            "time_text": _coerce_text(raw_extract.get("time_text")) or due_at,
            "location_text": _coerce_text(raw_extract.get("location_text")),
        }
        label_row.notes = "generated by v2 ingestion gmail parser"

        db.query(EmailActionItem).filter(EmailActionItem.email_id == message_id).delete(synchronize_session=False)
        if event_type in ACTIONABLE_EVENT_TYPES:
            db.add(
                EmailActionItem(
                    email_id=message_id,
                    action="Review extracted email event",
                    due_iso=due_at,
                    where_text=_coerce_text(raw_extract.get("location_text")),
                )
            )

        analysis_row = db.get(EmailRuleAnalysis, message_id)
        if analysis_row is None:
            analysis_row = EmailRuleAnalysis(email_id=message_id)
            db.add(analysis_row)
        analysis_row.event_flags = {key: key == event_type for key in EMAIL_EVENT_KEYS}
        snippet = subject or message_id
        analysis_row.matched_snippets = [{"rule": event_type or "other", "snippet": snippet[:240]}]
        analysis_row.drop_reason_codes = [] if event_type in ACTIONABLE_EVENT_TYPES else ["non_actionable_event_type"]

        route_row = db.get(EmailRoute, message_id)
        if route_row is None:
            route_row = EmailRoute(
                email_id=message_id,
                route="archive",
                routed_at=applied_at,
                viewed_at=None,
                notified_at=None,
            )
            db.add(route_row)
        else:
            route_row.route = "archive"
            route_row.routed_at = applied_at


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
    return {
        "title": payload.get("title"),
        "start_at_utc": payload.get("start_at_utc"),
        "end_at_utc": payload.get("end_at_utc"),
        "event_type": payload.get("event_type"),
    }


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
    adjusted["title"] = old_title
    enrichment = adjusted.get("enrichment") if isinstance(adjusted.get("enrichment"), dict) else {}
    enrichment["title_aliases"] = _append_alias(enrichment.get("title_aliases"), new_title, limit=24)
    adjusted["enrichment"] = enrichment
    return adjusted


def _extract_observation_title_and_times(payload: dict) -> tuple[str, str, str] | None:
    source_canonical = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}
    title = source_canonical.get("source_title")
    start = source_canonical.get("source_dtstart_utc")
    end = source_canonical.get("source_dtend_utc")
    if not isinstance(title, str):
        title = payload.get("title") if isinstance(payload.get("title"), str) else None
    if not isinstance(start, str):
        start = payload.get("start_at_utc") if isinstance(payload.get("start_at_utc"), str) else None
    if not isinstance(end, str):
        end = payload.get("end_at_utc") if isinstance(payload.get("end_at_utc"), str) else None
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
) -> int:
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

    return len(created_changes)


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
    if not isinstance(start_raw, str):
        start_raw = payload.get("start_at_utc") if isinstance(payload.get("start_at_utc"), str) else payload.get("start_at")
    if not isinstance(end_raw, str):
        end_raw = payload.get("end_at_utc") if isinstance(payload.get("end_at_utc"), str) else payload.get("end_at")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        return None
    start_at = _parse_iso_datetime(start_raw, field="start_at_utc", uid=merge_key)
    end_at = _parse_iso_datetime(end_raw, field="end_at_utc", uid=merge_key)
    if end_at <= start_at:
        return None

    title = source_canonical.get("source_title") if isinstance(source_canonical.get("source_title"), str) else None
    if not isinstance(title, str):
        title = payload.get("title") if isinstance(payload.get("title"), str) else None
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


def _coerce_calendar_payload(*, payload: dict, source_id: int, fallback_index: int) -> CanonicalEventInput:
    source_canonical = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}
    uid_value = payload.get("uid")
    uid = uid_value.strip() if isinstance(uid_value, str) else ""
    if not uid:
        uid_raw = source_canonical.get("external_event_id")
        uid = uid_raw.strip() if isinstance(uid_raw, str) else ""
    if not uid:
        uid = f"calendar-{source_id}-{fallback_index}"

    title_raw = source_canonical.get("source_title") if isinstance(source_canonical.get("source_title"), str) else payload.get("title")
    if not isinstance(title_raw, str) or not title_raw.strip():
        raise RuntimeError(f"calendar record uid={uid} missing non-empty title")
    title = title_raw.strip()

    course_label_raw = payload.get("course_label")
    course_label = course_label_raw.strip() if isinstance(course_label_raw, str) and course_label_raw.strip() else "Unknown"

    start_value = source_canonical.get("source_dtstart_utc")
    end_value = source_canonical.get("source_dtend_utc")
    if not isinstance(start_value, str):
        start_value = payload.get("start_at_utc") if isinstance(payload.get("start_at_utc"), str) else payload.get("start_at")
    if not isinstance(end_value, str):
        end_value = payload.get("end_at_utc") if isinstance(payload.get("end_at_utc"), str) else payload.get("end_at")
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


def _extract_course_hints(raw_extract: dict) -> list[str]:
    candidates: list[str] = []

    course_hint = raw_extract.get("course_hint")
    if isinstance(course_hint, str) and course_hint.strip():
        candidates.append(course_hint.strip()[:64])

    course_hints = raw_extract.get("course_hints")
    if isinstance(course_hints, list):
        candidates.extend([item.strip()[:64] for item in course_hints if isinstance(item, str) and item.strip()])

    course = raw_extract.get("course")
    if isinstance(course, str) and course.strip():
        candidates.append(course.strip()[:64])

    course_alias = raw_extract.get("course_alias")
    if isinstance(course_alias, list):
        candidates.extend([item.strip()[:64] for item in course_alias if isinstance(item, str) and item.strip()])

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.upper()
        if key in seen:
            continue
        deduped.append(candidate)
        seen.add(key)
        if len(deduped) >= 3:
            break
    return deduped


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
