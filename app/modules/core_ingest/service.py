from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
    IngestApplyLog,
    IngestResult,
    Input,
    InputSource,
    InputType,
    ReviewStatus,
    SourceEventObservation,
    SourceKind,
    SyncRequest,
    SyncRequestStatus,
)
from app.modules.core_ingest.merge_engine import build_merge_key, choose_primary_observation
from app.modules.notify.service import enqueue_notifications_for_changes
from app.modules.sync.email_rules import ACTIONABLE_EVENT_TYPES
from app.modules.sync.types import CanonicalEventInput

GMAIL_EVENT_TYPES = ACTIONABLE_EVENT_TYPES | {"announcement", "grade", "other"}
EMAIL_EVENT_KEYS = sorted(ACTIONABLE_EVENT_TYPES | {"announcement", "grade", "other"})
COURSE_HINT_PATTERN = re.compile(r"\b([A-Za-z]{3,5})[\s_\-]*([0-9]{1,3}[A-Za-z]?)\b")


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
    affected_merge_keys: set[str] = set()
    seen_external_ids: set[str] = set()

    for index, record in enumerate(records):
        if not isinstance(record, dict) or record.get("record_type") != "calendar.event.extracted":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise RuntimeError(f"calendar record payload at index {index} must be object")

        event = _coerce_calendar_payload(payload=payload, source_id=source.id, fallback_index=index)
        confidence_raw = payload.get("raw_confidence")
        confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.5
        merge_key = build_merge_key(
            course_label=event.course_label,
            title=event.title,
            start_at=event.start_at_utc,
            end_at=event.end_at_utc,
            event_type=None,
        )
        observation_payload = {
            "uid": event.uid,
            "title": event.title,
            "course_label": event.course_label,
            "start_at_utc": event.start_at_utc.isoformat(),
            "end_at_utc": event.end_at_utc.isoformat(),
            "confidence": confidence,
            "raw_confidence": confidence,
            "event_type": "event",
        }
        seen_external_ids.add(event.uid)
        affected_merge_keys.update(
            _upsert_observation(
                db=db,
                source=source,
                external_event_id=event.uid,
                merge_key=merge_key,
                event_payload=observation_payload,
                applied_at=applied_at,
                request_id=request_id,
            )
        )

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
        affected_merge_keys.add(row.merge_key)

    return affected_merge_keys


def _apply_gmail_observations(
    *,
    db: Session,
    source: InputSource,
    records: list[dict],
    applied_at: datetime,
    request_id: str,
) -> set[str]:
    affected_merge_keys: set[str] = set()

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
        due_at = _parse_optional_iso_datetime(payload.get("due_at"))
        is_actionable = event_type in ACTIONABLE_EVENT_TYPES and due_at is not None

        if not is_actionable:
            affected_merge_keys.update(
                _deactivate_observation(
                    db=db,
                    source_id=source.id,
                    external_event_id=external_event_id,
                    applied_at=applied_at,
                    request_id=request_id,
                )
            )
            continue

        subject = payload.get("subject") if isinstance(payload.get("subject"), str) else None
        raw_extract = payload.get("raw_extract") if isinstance(payload.get("raw_extract"), dict) else {}
        course_hints = _extract_course_hints(raw_extract)
        if not course_hints:
            course_hints = _extract_course_hints_from_text(subject)
        course_label = course_hints[0] if course_hints else "Unknown"
        title = (subject or f"Email event {external_event_id}").strip()[:512]
        end_at = due_at + timedelta(hours=1)

        confidence_raw = payload.get("confidence")
        confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.5
        merge_key = build_merge_key(
            course_label=course_label,
            title=title,
            start_at=due_at,
            end_at=end_at,
            event_type=None,
        )

        observation_payload = {
            "uid": f"gmail:{external_event_id}",
            "title": title,
            "course_label": course_label,
            "start_at_utc": due_at.isoformat(),
            "end_at_utc": end_at.isoformat(),
            "confidence": confidence,
            "raw_confidence": confidence,
            "event_type": event_type,
            "message_id": external_event_id,
        }

        affected_merge_keys.update(
            _upsert_observation(
                db=db,
                source=source,
                external_event_id=external_event_id,
                merge_key=merge_key,
                event_payload=observation_payload,
                applied_at=applied_at,
                request_id=request_id,
            )
        )

    return affected_merge_keys


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
    event_hash = _compute_payload_hash(event_payload)
    row = db.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.external_event_id == external_event_id,
        )
    )
    if row is None:
        db.add(
            SourceEventObservation(
                user_id=source.user_id,
                source_id=source.id,
                source_kind=source.source_kind,
                provider=source.provider,
                external_event_id=external_event_id,
                merge_key=merge_key,
                event_payload=event_payload,
                event_hash=event_hash,
                observed_at=applied_at,
                is_active=True,
                last_request_id=request_id,
            )
        )
        affected_merge_keys.add(merge_key)
        return affected_merge_keys

    old_merge_key = row.merge_key
    row.merge_key = merge_key
    row.event_payload = event_payload
    row.event_hash = event_hash
    row.observed_at = applied_at
    row.is_active = True
    row.last_request_id = request_id
    affected_merge_keys.add(old_merge_key)
    affected_merge_keys.add(merge_key)
    return affected_merge_keys


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
        enqueue_notifications_for_changes(
            db,
            input=canonical_input,
            changes=created_changes,
            deliver_after=applied_at,
            enqueue_reason="review_pending_created",
        )

    return len(created_changes)


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
    start_raw = payload.get("start_at_utc")
    end_raw = payload.get("end_at_utc")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        return None
    start_at = _parse_iso_datetime(start_raw, field="start_at_utc", uid=merge_key)
    end_at = _parse_iso_datetime(end_raw, field="end_at_utc", uid=merge_key)
    if end_at <= start_at:
        return None

    title = payload.get("title") if isinstance(payload.get("title"), str) else None
    course_label = payload.get("course_label") if isinstance(payload.get("course_label"), str) else None
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
        and str(before_json.get("course_label") or "") == str(after_json.get("course_label") or "")
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
    uid_value = payload.get("uid")
    uid = uid_value.strip() if isinstance(uid_value, str) else ""
    if not uid:
        uid = f"calendar-{source_id}-{fallback_index}"

    title_raw = payload.get("title")
    if not isinstance(title_raw, str) or not title_raw.strip():
        raise RuntimeError(f"calendar record uid={uid} missing non-empty title")
    title = title_raw.strip()

    course_label_raw = payload.get("course_label")
    course_label = course_label_raw.strip() if isinstance(course_label_raw, str) and course_label_raw.strip() else "Unknown"

    start_at = _parse_iso_datetime(payload.get("start_at"), field="start_at", uid=uid)
    end_at = _parse_iso_datetime(payload.get("end_at"), field="end_at", uid=uid)
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
    course_hint = raw_extract.get("course_hint")
    if isinstance(course_hint, str) and course_hint.strip():
        return [course_hint.strip()[:64]]
    course_hints = raw_extract.get("course_hints")
    if isinstance(course_hints, list):
        out = [item.strip()[:64] for item in course_hints if isinstance(item, str) and item.strip()]
        if out:
            return out[:3]
    return []


def _extract_course_hints_from_text(value: object) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return []
    hints: list[str] = []
    seen: set[str] = set()
    for match in COURSE_HINT_PATTERN.finditer(value):
        normalized = f"{match.group(1).upper()}{match.group(2).upper()}"
        if normalized in seen:
            continue
        hints.append(normalized[:64])
        seen.add(normalized)
        if len(hints) >= 3:
            break
    return hints


def _coerce_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
