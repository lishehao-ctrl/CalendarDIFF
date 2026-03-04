from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, joinedload

from app.contracts.events import new_event
from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.db.models import (
    Change,
    ChangeType,
    Event,
    Input,
    InputType,
    IntegrationOutbox,
    Notification,
    NotificationChannel,
    NotificationStatus,
    OutboxStatus,
    ReviewStatus,
    User,
)


class ReviewChangeNotFoundError(RuntimeError):
    pass


class EvidencePathError(RuntimeError):
    pass


class ReviewChangeEvidenceNotFoundError(RuntimeError):
    pass


class ReviewChangeEvidenceReadError(RuntimeError):
    pass


class ManualCorrectionNotFoundError(RuntimeError):
    pass


class ManualCorrectionValidationError(RuntimeError):
    pass


SUMMARY_TIME_FIELDS = ("start_at_utc", "internal_date", "due_at", "end_at_utc")
PREVIEW_MAX_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


def list_review_changes(
    db: Session,
    *,
    user_id: int,
    review_status: str,
    source_id: int | None,
    limit: int,
    offset: int,
) -> list[dict]:
    stmt = (
        select(Change, Input, Notification)
        .options(joinedload(Change.before_snapshot), joinedload(Change.after_snapshot))
        .join(Input, Input.id == Change.input_id)
        .outerjoin(
            Notification,
            and_(
                Notification.change_id == Change.id,
                Notification.channel == NotificationChannel.EMAIL,
            ),
        )
        .where(Input.user_id == user_id)
    )

    if review_status == "pending":
        stmt = stmt.where(Change.review_status == ReviewStatus.PENDING)
    elif review_status == "approved":
        stmt = stmt.where(Change.review_status == ReviewStatus.APPROVED)
    elif review_status == "rejected":
        stmt = stmt.where(Change.review_status == ReviewStatus.REJECTED)

    db_offset = 0 if source_id is not None else offset
    db_limit = (limit + offset + 512) if source_id is not None else limit
    stmt = stmt.order_by(Change.detected_at.desc(), Change.id.desc()).offset(db_offset).limit(db_limit)
    rows = db.execute(stmt).all()

    now = datetime.now(timezone.utc)
    output: list[dict] = []
    for row, input_row, notification_row in rows:
        sources = _parse_sources(row.proposal_sources_json)
        proposal_source_ids = _extract_proposal_source_ids(row)
        resolved_source_id = proposal_source_ids[0] if proposal_source_ids else row.input_id
        resolved_source_kind = _extract_primary_source_kind(row) or _to_source_kind_value(input_row.type)
        if source_id is not None and source_id not in {resolved_source_id, *proposal_source_ids}:
            continue
        priority_rank = 0 if resolved_source_kind == "email" else 1
        priority_label = "high" if priority_rank == 0 else "normal"
        notification_state, deliver_after = _read_notification_state(notification_row, now=now)
        output.append(
            {
                "id": row.id,
                "event_uid": row.event_uid,
                "change_type": row.change_type.value,
                "detected_at": row.detected_at,
                "review_status": row.review_status.value,
                "before_json": row.before_json,
                "after_json": row.after_json,
                "proposal_merge_key": row.proposal_merge_key,
                "proposal_sources": sources,
                "source_id": resolved_source_id,
                "viewed_at": row.viewed_at,
                "viewed_note": row.viewed_note,
                "reviewed_at": row.reviewed_at,
                "review_note": row.review_note,
                "source_kind": resolved_source_kind,
                "priority_rank": priority_rank,
                "priority_label": priority_label,
                "notification_state": notification_state,
                "deliver_after": deliver_after,
                "change_summary": _build_change_summary(change=row, input_row=input_row),
            }
        )

    if source_id is not None:
        return output[offset : offset + limit]
    return output


def mark_review_change_viewed(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    viewed: bool,
    note: str | None,
) -> Change:
    row = db.scalar(
        select(Change)
        .join(Input, Input.id == Change.input_id)
        .where(Change.id == change_id, Input.user_id == user_id)
        .with_for_update()
    )
    if row is None:
        raise ReviewChangeNotFoundError("Review change not found")

    if viewed:
        row.viewed_at = datetime.now(timezone.utc)
        row.viewed_note = note
    else:
        row.viewed_at = None
        row.viewed_note = None

    db.commit()
    db.refresh(row)
    return row


def decide_review_change(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    decision: str,
    note: str | None,
) -> tuple[Change, bool]:
    row = db.scalar(
        select(Change)
        .join(Input, Input.id == Change.input_id)
        .where(Change.id == change_id, Input.user_id == user_id)
        .with_for_update()
    )
    if row is None:
        raise ReviewChangeNotFoundError("Review change not found")

    if row.review_status != ReviewStatus.PENDING:
        return row, True

    now = datetime.now(timezone.utc)
    if decision == "approve":
        _apply_change_to_canonical_event(db=db, change=row)
        row.review_status = ReviewStatus.APPROVED
    else:
        row.review_status = ReviewStatus.REJECTED

    row.reviewed_at = now
    row.review_note = note
    row.reviewed_by_user_id = user_id

    event = new_event(
        event_type=f"review.decision.{decision}",
        aggregate_type="change",
        aggregate_id=str(row.id),
        payload={
            "change_id": row.id,
            "event_uid": row.event_uid,
            "review_status": row.review_status.value,
            "reviewed_by_user_id": user_id,
            "reviewed_at": now.isoformat(),
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

    db.commit()
    db.refresh(row)
    return row, False


def preview_review_change_evidence(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    side: Literal["before", "after"],
) -> dict:
    row, resolved = _resolve_change_evidence_file(db, user_id=user_id, change_id=change_id, side=side)
    try:
        content_bytes = resolved.read_bytes()
    except FileNotFoundError as exc:
        raise ReviewChangeEvidenceNotFoundError("Evidence file not found") from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.error("failed to read evidence preview error=%s", sanitize_log_message(str(exc)))
        raise ReviewChangeEvidenceReadError("Failed to prepare evidence preview") from exc

    truncated = len(content_bytes) > PREVIEW_MAX_BYTES
    preview_text = _build_evidence_preview_text(content_bytes)
    return {
        "side": side,
        "content_type": "text/calendar",
        "truncated": truncated,
        "filename": f"change-{row.id}-{side}.ics",
        "event_count": 0,
        "events": [],
        "preview_text": preview_text,
    }


def preview_manual_correction(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
    event_uid: str | None,
    due_at: str,
    title: str | None,
    course_label: str | None,
    reason: str | None,
) -> dict:
    del reason
    user = _load_user_or_raise(db, user_id=user_id)
    canonical_input = _ensure_canonical_input_for_user(db=db, user_id=user_id)
    resolved_event_uid = resolve_target_event_uid(
        db,
        user_id=user_id,
        change_id=change_id,
        event_uid=event_uid,
    )
    base_snapshot, existing_event = load_base_snapshot(
        db=db,
        canonical_input_id=canonical_input.id,
        event_uid=resolved_event_uid,
    )
    candidate_after = build_candidate_after(
        event_uid=resolved_event_uid,
        base_snapshot=base_snapshot,
        due_at=due_at,
        title=title,
        course_label=course_label,
        timezone_name=user.timezone_name,
    )
    will_reject_pending_change_ids = _list_pending_change_ids(
        db=db,
        canonical_input_id=canonical_input.id,
        event_uid=resolved_event_uid,
    )
    idempotent = existing_event is not None and _event_json_equivalent(base_snapshot, candidate_after)
    delta_seconds = _safe_delta_seconds(before_json=base_snapshot, after_json=candidate_after)
    return {
        "event_uid": resolved_event_uid,
        "base": _manual_payload_from_event_json(base_snapshot),
        "candidate_after": _manual_payload_from_event_json(candidate_after),
        "delta_seconds": delta_seconds,
        "will_reject_pending_change_ids": will_reject_pending_change_ids,
        "idempotent": idempotent,
    }


def apply_manual_correction(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
    event_uid: str | None,
    due_at: str,
    title: str | None,
    course_label: str | None,
    reason: str | None,
) -> dict:
    user = _load_user_or_raise(db, user_id=user_id)
    canonical_input = _ensure_canonical_input_for_user(db=db, user_id=user_id)
    resolved_event_uid = resolve_target_event_uid(
        db,
        user_id=user_id,
        change_id=change_id,
        event_uid=event_uid,
    )
    existing_event = db.scalar(
        select(Event)
        .where(
            Event.input_id == canonical_input.id,
            Event.uid == resolved_event_uid,
        )
        .with_for_update()
    )
    base_snapshot, base_existing_event = load_base_snapshot(
        db=db,
        canonical_input_id=canonical_input.id,
        event_uid=resolved_event_uid,
        existing_event=existing_event,
    )
    candidate_after = build_candidate_after(
        event_uid=resolved_event_uid,
        base_snapshot=base_snapshot,
        due_at=due_at,
        title=title,
        course_label=course_label,
        timezone_name=user.timezone_name,
    )
    idempotent = base_existing_event is not None and _event_json_equivalent(base_snapshot, candidate_after)
    if idempotent:
        return {
            "applied": True,
            "idempotent": True,
            "correction_change_id": None,
            "event_uid": resolved_event_uid,
            "rejected_pending_change_ids": [],
            "event": _manual_payload_from_event_json(candidate_after),
        }

    now = datetime.now(timezone.utc)
    parsed_after = _parse_after_json(resolved_event_uid, candidate_after)
    if parsed_after is None:
        raise ManualCorrectionValidationError("manual correction produced invalid event payload")

    if existing_event is None:
        db.add(
            Event(
                input_id=canonical_input.id,
                uid=resolved_event_uid,
                course_label=parsed_after["course_label"],
                title=parsed_after["title"],
                start_at_utc=parsed_after["start_at_utc"],
                end_at_utc=parsed_after["end_at_utc"],
            )
        )
        change_type = ChangeType.CREATED
        before_json = None
        delta_seconds = None
    else:
        existing_event.course_label = parsed_after["course_label"]
        existing_event.title = parsed_after["title"]
        existing_event.start_at_utc = parsed_after["start_at_utc"]
        existing_event.end_at_utc = parsed_after["end_at_utc"]
        change_type = ChangeType.DUE_CHANGED
        before_json = base_snapshot
        delta_seconds = _safe_delta_seconds(before_json=base_snapshot, after_json=candidate_after)

    reason_text = (reason or "").strip()
    manual_note = f"manual_correction:{reason_text}" if reason_text else "manual_correction"
    correction_change = Change(
        input_id=canonical_input.id,
        event_uid=resolved_event_uid,
        change_type=change_type,
        detected_at=now,
        before_json=before_json,
        after_json=candidate_after,
        delta_seconds=delta_seconds,
        viewed_at=None,
        viewed_note=None,
        review_status=ReviewStatus.APPROVED,
        reviewed_at=now,
        review_note=manual_note,
        reviewed_by_user_id=user_id,
        proposal_merge_key=resolved_event_uid,
        proposal_sources_json=[],
        before_snapshot_id=None,
        after_snapshot_id=None,
        evidence_keys=None,
    )
    db.add(correction_change)
    db.flush()
    correction_change_id = int(correction_change.id)
    rejected_pending_change_ids = reject_conflicting_pending_changes(
        db=db,
        canonical_input_id=canonical_input.id,
        event_uid=resolved_event_uid,
        reviewed_at=now,
        reviewed_by_user_id=user_id,
        correction_change_id=correction_change_id,
    )
    emit_manual_correction_audit_event(
        db=db,
        change_id=correction_change_id,
        event_uid=resolved_event_uid,
        reviewed_by_user_id=user_id,
        reviewed_at=now,
        rejected_pending_change_ids=rejected_pending_change_ids,
    )
    db.commit()
    return {
        "applied": True,
        "idempotent": False,
        "correction_change_id": correction_change_id,
        "event_uid": resolved_event_uid,
        "rejected_pending_change_ids": rejected_pending_change_ids,
        "event": _manual_payload_from_event_json(candidate_after),
    }


def _apply_change_to_canonical_event(*, db: Session, change: Change) -> None:
    existing = db.scalar(
        select(Event).where(
            Event.input_id == change.input_id,
            Event.uid == change.event_uid,
        )
    )

    if change.change_type == ChangeType.REMOVED:
        if existing is not None:
            db.delete(existing)
        return

    after_json = change.after_json if isinstance(change.after_json, dict) else None
    if after_json is None:
        return

    parsed = _parse_after_json(change.event_uid, after_json)
    if parsed is None:
        return

    if existing is None:
        db.add(
            Event(
                input_id=change.input_id,
                uid=change.event_uid,
                course_label=parsed["course_label"],
                title=parsed["title"],
                start_at_utc=parsed["start_at_utc"],
                end_at_utc=parsed["end_at_utc"],
            )
        )
        return

    existing.course_label = parsed["course_label"]
    existing.title = parsed["title"]
    existing.start_at_utc = parsed["start_at_utc"]
    existing.end_at_utc = parsed["end_at_utc"]


def _parse_after_json(event_uid: str, payload: dict) -> dict | None:
    del event_uid
    start_raw = payload.get("start_at_utc")
    end_raw = payload.get("end_at_utc")
    title_raw = payload.get("title")
    course_label_raw = payload.get("course_label")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        return None
    start_at = _parse_iso_datetime(start_raw)
    end_at = _parse_iso_datetime(end_raw)
    if start_at is None or end_at is None or end_at <= start_at:
        return None
    title = title_raw.strip()[:512] if isinstance(title_raw, str) and title_raw.strip() else "Untitled"
    course_label = course_label_raw.strip()[:64] if isinstance(course_label_raw, str) and course_label_raw.strip() else "Unknown"
    return {
        "title": title,
        "course_label": course_label,
        "start_at_utc": start_at,
        "end_at_utc": end_at,
    }


def _parse_iso_datetime(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_sources(raw_sources: object) -> list[dict]:
    if not isinstance(raw_sources, list):
        return []
    out: list[dict] = []
    for item in raw_sources:
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id")
        if not isinstance(source_id, int):
            continue
        source_kind = item.get("source_kind") if isinstance(item.get("source_kind"), str) else None
        provider = item.get("provider") if isinstance(item.get("provider"), str) else None
        external_event_id = item.get("external_event_id") if isinstance(item.get("external_event_id"), str) else None
        confidence_raw = item.get("confidence")
        confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else None
        out.append(
            {
                "source_id": source_id,
                "source_kind": source_kind,
                "provider": provider,
                "external_event_id": external_event_id,
                "confidence": confidence,
            }
        )
    return out


def _to_source_kind_value(input_type: InputType) -> str:
    if input_type == InputType.ICS:
        return "calendar"
    return "email"


def _extract_proposal_source_ids(change: Change) -> list[int]:
    sources = change.proposal_sources_json if isinstance(change.proposal_sources_json, list) else []
    out: list[int] = []
    for row in sources:
        if not isinstance(row, dict):
            continue
        source_id = row.get("source_id")
        if isinstance(source_id, int):
            out.append(source_id)
    return out


def _extract_primary_source_kind(change: Change) -> str | None:
    sources = change.proposal_sources_json if isinstance(change.proposal_sources_json, list) else []
    for row in sources:
        if not isinstance(row, dict):
            continue
        source_kind = row.get("source_kind")
        if isinstance(source_kind, str):
            normalized = source_kind.strip().lower()
            if normalized in {"calendar", "email"}:
                return normalized
    return None


def _read_notification_state(
    row: Notification | None,
    *,
    now: datetime,
) -> tuple[str | None, datetime | None]:
    if row is None:
        return None, None

    deliver_after = row.deliver_after
    if row.status == NotificationStatus.PENDING:
        if deliver_after > now and row.enqueue_reason == "email_priority_delay":
            return "queued_delayed_by_email_priority", deliver_after
        if deliver_after > now:
            return "queued_delayed", deliver_after
        return "queued", deliver_after
    if row.status == NotificationStatus.SENT:
        return "sent", deliver_after
    if row.status == NotificationStatus.FAILED:
        return "failed", deliver_after
    return None, deliver_after


def _build_change_summary(*, change: Change, input_row: Input) -> dict:
    source_label = input_row.display_label if isinstance(input_row.display_label, str) else None
    source_kind = _to_source_kind_value(input_row.type) if isinstance(input_row.type, InputType) else None

    before_payload = change.before_json if isinstance(change.before_json, dict) else None
    after_payload = change.after_json if isinstance(change.after_json, dict) else None

    return {
        "old": {
            "value_time": _extract_value_time(before_payload),
            "source_label": source_label,
            "source_kind": source_kind,
            "source_observed_at": change.before_snapshot.retrieved_at if change.before_snapshot is not None else None,
        },
        "new": {
            "value_time": _extract_value_time(after_payload),
            "source_label": source_label,
            "source_kind": source_kind,
            "source_observed_at": change.after_snapshot.retrieved_at if change.after_snapshot is not None else None,
        },
    }


def _extract_snapshot_evidence_key(raw_evidence_key: object) -> dict[str, Any] | None:
    if not isinstance(raw_evidence_key, dict):
        return None
    return raw_evidence_key


def _extract_snapshot_evidence_path(raw_evidence_key: object) -> str | None:
    key = _extract_snapshot_evidence_key(raw_evidence_key)
    if key is None:
        return None
    path_value = key.get("path")
    if isinstance(path_value, str) and path_value:
        return path_value
    return None


def _resolve_change_evidence_file(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    side: Literal["before", "after"],
) -> tuple[Change, Path]:
    row = db.scalar(
        select(Change)
        .join(Input, Input.id == Change.input_id)
        .options(joinedload(Change.before_snapshot), joinedload(Change.after_snapshot))
        .where(Change.id == change_id, Input.user_id == user_id)
    )
    if row is None:
        raise ReviewChangeNotFoundError("Review change not found")

    snapshot = row.before_snapshot if side == "before" else row.after_snapshot
    evidence_path = _extract_snapshot_evidence_path(snapshot.raw_evidence_key if snapshot is not None else None)
    if evidence_path is None:
        raise ReviewChangeEvidenceNotFoundError("Evidence file not found")

    try:
        resolved = _resolve_evidence_file_path(evidence_path)
    except EvidencePathError as exc:
        raise ReviewChangeEvidenceNotFoundError("Evidence file not found") from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.error("failed to resolve evidence path error=%s", sanitize_log_message(str(exc)))
        raise ReviewChangeEvidenceReadError("Failed to prepare evidence file") from exc

    if not resolved.exists() or not resolved.is_file():
        raise ReviewChangeEvidenceNotFoundError("Evidence file not found")
    return row, resolved


def _build_evidence_preview_text(content_bytes: bytes) -> str:
    preview_bytes = content_bytes[:PREVIEW_MAX_BYTES]
    return preview_bytes.decode("utf-8", errors="replace")


def _resolve_evidence_file_path(raw_path: str) -> Path:
    normalized = raw_path.strip() if isinstance(raw_path, str) else ""
    if not normalized:
        raise EvidencePathError("evidence path is empty")

    settings = get_settings()
    configured_base = Path(settings.evidence_dir).expanduser()
    if configured_base.is_absolute():
        base_dir = configured_base.resolve()
    else:
        base_dir = (Path.cwd() / configured_base).resolve()

    path_obj = Path(normalized).expanduser()
    if path_obj.is_absolute():
        resolved = path_obj.resolve()
    else:
        resolved = (base_dir / path_obj).resolve()

    if not _is_relative_to(resolved, base_dir):
        raise EvidencePathError("evidence path escaped base directory")
    return resolved


def _extract_value_time(payload: dict[str, Any] | None) -> datetime | None:
    if payload is None:
        return None
    for key in SUMMARY_TIME_FIELDS:
        parsed = _coerce_datetime(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return _as_utc(parsed)


def resolve_target_event_uid(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
    event_uid: str | None,
) -> str:
    normalized_event_uid = event_uid.strip() if isinstance(event_uid, str) else ""
    if event_uid is not None and not normalized_event_uid:
        raise ManualCorrectionValidationError("target.event_uid must not be blank")
    if change_id is None and not normalized_event_uid:
        raise ManualCorrectionValidationError("target.change_id or target.event_uid is required")

    change_event_uid: str | None = None
    if change_id is not None:
        row = db.scalar(
            select(Change)
            .join(Input, Input.id == Change.input_id)
            .where(Change.id == change_id, Input.user_id == user_id)
            .limit(1)
        )
        if row is None:
            raise ManualCorrectionNotFoundError("target change not found")
        change_event_uid = row.event_uid

    if change_event_uid is not None and normalized_event_uid and change_event_uid != normalized_event_uid:
        raise ManualCorrectionValidationError("target.change_id and target.event_uid must reference the same event_uid")

    resolved = normalized_event_uid or change_event_uid
    if not isinstance(resolved, str) or not resolved:
        raise ManualCorrectionValidationError("unable to resolve target event_uid")
    return resolved


def load_base_snapshot(
    *,
    db: Session,
    canonical_input_id: int,
    event_uid: str,
    existing_event: Event | None = None,
) -> tuple[dict, Event | None]:
    event_row = existing_event
    if event_row is None:
        event_row = db.scalar(
            select(Event).where(
                Event.input_id == canonical_input_id,
                Event.uid == event_uid,
            )
        )
    if event_row is not None:
        return _event_row_to_json(event_row), event_row

    pending_row = db.scalar(
        select(Change)
        .where(
            Change.input_id == canonical_input_id,
            Change.event_uid == event_uid,
            Change.review_status == ReviewStatus.PENDING,
            Change.after_json.is_not(None),
        )
        .order_by(Change.id.desc())
        .limit(1)
    )
    if pending_row is not None and isinstance(pending_row.after_json, dict):
        parsed = _parse_after_json(event_uid, pending_row.after_json)
        if parsed is not None:
            return {
                "uid": event_uid,
                "title": parsed["title"],
                "course_label": parsed["course_label"],
                "start_at_utc": parsed["start_at_utc"].isoformat(),
                "end_at_utc": parsed["end_at_utc"].isoformat(),
            }, None
    raise ManualCorrectionNotFoundError("target event not found in canonical or pending proposals")


def build_candidate_after(
    *,
    event_uid: str,
    base_snapshot: dict,
    due_at: str,
    title: str | None,
    course_label: str | None,
    timezone_name: str,
) -> dict:
    due_at_utc = normalize_due_at_with_user_timezone(due_at, timezone_name=timezone_name)
    next_end_at = due_at_utc + timedelta(hours=1)
    next_title = _coalesce_patch_text(title, fallback=str(base_snapshot.get("title") or "Untitled"), max_len=512)
    next_course_label = _coalesce_patch_text(
        course_label,
        fallback=str(base_snapshot.get("course_label") or "Unknown"),
        max_len=64,
    )
    return {
        "uid": event_uid,
        "title": next_title,
        "course_label": next_course_label,
        "start_at_utc": due_at_utc.isoformat(),
        "end_at_utc": next_end_at.isoformat(),
    }


def normalize_due_at_with_user_timezone(value: str, *, timezone_name: str) -> datetime:
    raw = value.strip() if isinstance(value, str) else ""
    if not raw:
        raise ManualCorrectionValidationError("patch.due_at must not be blank")
    local_tz = _resolve_timezone_name(timezone_name)
    if "T" not in raw:
        try:
            due_date = date.fromisoformat(raw)
        except ValueError as exc:
            raise ManualCorrectionValidationError("patch.due_at must be valid date or datetime") from exc
        local_due = datetime(
            due_date.year,
            due_date.month,
            due_date.day,
            23,
            59,
            0,
            tzinfo=local_tz,
        )
        return local_due.astimezone(timezone.utc)

    normalized = raw[:-1] + "+00:00" if raw.lower().endswith("z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ManualCorrectionValidationError("patch.due_at must be valid date or datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(timezone.utc)


def reject_conflicting_pending_changes(
    *,
    db: Session,
    canonical_input_id: int,
    event_uid: str,
    reviewed_at: datetime,
    reviewed_by_user_id: int,
    correction_change_id: int,
) -> list[int]:
    pending_rows = db.scalars(
        select(Change)
        .where(
            Change.input_id == canonical_input_id,
            Change.event_uid == event_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
        .with_for_update()
    ).all()
    rejected_ids: list[int] = []
    for row in pending_rows:
        if row.id == correction_change_id:
            continue
        row.review_status = ReviewStatus.REJECTED
        row.reviewed_at = reviewed_at
        row.review_note = f"superseded_by_manual_correction:{correction_change_id}"
        row.reviewed_by_user_id = reviewed_by_user_id
        rejected_ids.append(int(row.id))
    rejected_ids.sort()
    return rejected_ids


def emit_manual_correction_audit_event(
    *,
    db: Session,
    change_id: int,
    event_uid: str,
    reviewed_by_user_id: int,
    reviewed_at: datetime,
    rejected_pending_change_ids: list[int],
) -> None:
    event = new_event(
        event_type="review.decision.approved",
        aggregate_type="change",
        aggregate_id=str(change_id),
        payload={
            "change_id": change_id,
            "event_uid": event_uid,
            "review_status": ReviewStatus.APPROVED.value,
            "reviewed_by_user_id": reviewed_by_user_id,
            "reviewed_at": reviewed_at.isoformat(),
            "decision_origin": "manual_correction",
            "correction_change_id": change_id,
            "rejected_pending_change_ids": list(rejected_pending_change_ids),
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


def _load_user_or_raise(db: Session, *, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise ManualCorrectionNotFoundError("user not found")
    return user


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


def _resolve_timezone_name(value: str | None) -> ZoneInfo:
    normalized = (value or "").strip() or "UTC"
    try:
        return ZoneInfo(normalized)
    except Exception:
        return ZoneInfo("UTC")


def _coalesce_patch_text(value: str | None, *, fallback: str, max_len: int) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped[:max_len]
    fallback_clean = fallback.strip()
    if fallback_clean:
        return fallback_clean[:max_len]
    return "Unknown"[:max_len]


def _list_pending_change_ids(*, db: Session, canonical_input_id: int, event_uid: str) -> list[int]:
    rows = db.scalars(
        select(Change.id)
        .where(
            Change.input_id == canonical_input_id,
            Change.event_uid == event_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
        .order_by(Change.id.asc())
    ).all()
    return [int(row_id) for row_id in rows if isinstance(row_id, int)]


def _manual_payload_from_event_json(payload: dict) -> dict:
    start_raw = payload.get("start_at_utc")
    end_raw = payload.get("end_at_utc")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        raise ManualCorrectionValidationError("event payload missing start/end timestamps")
    start_at = _parse_iso_datetime(start_raw)
    end_at = _parse_iso_datetime(end_raw)
    if start_at is None or end_at is None:
        raise ManualCorrectionValidationError("event payload contains invalid timestamps")
    uid = payload.get("uid")
    title = payload.get("title")
    course_label = payload.get("course_label")
    if not isinstance(uid, str) or not uid.strip():
        raise ManualCorrectionValidationError("event payload missing uid")
    return {
        "uid": uid.strip(),
        "title": str(title or "Untitled")[:512],
        "course_label": str(course_label or "Unknown")[:64],
        "start_at_utc": start_at,
        "end_at_utc": end_at,
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
    before = _parse_iso_datetime(before_raw)
    after = _parse_iso_datetime(after_raw)
    if before is None or after is None:
        return None
    return int((after - before).total_seconds())


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
