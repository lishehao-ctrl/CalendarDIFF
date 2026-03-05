from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.db.models import (
    Change,
    ChangeType,
    Event,
    Input,
    InputType,
    IntegrationOutbox,
    OutboxStatus,
    ReviewStatus,
    User,
)
from app.modules.review_changes.change_decision_service import (
    event_json_equivalent,
    event_row_to_json,
    parse_after_json,
    parse_iso_datetime,
    safe_delta_seconds,
)


class ManualCorrectionNotFoundError(RuntimeError):
    pass


class ManualCorrectionValidationError(RuntimeError):
    pass


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
    user = load_user_or_raise(db, user_id=user_id)
    canonical_input = ensure_canonical_input_for_user(db=db, user_id=user_id)
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
    will_reject_pending_change_ids = list_pending_change_ids(
        db=db,
        canonical_input_id=canonical_input.id,
        event_uid=resolved_event_uid,
    )
    idempotent = existing_event is not None and event_json_equivalent(base_snapshot, candidate_after)
    delta_seconds = safe_delta_seconds(before_json=base_snapshot, after_json=candidate_after)
    return {
        "event_uid": resolved_event_uid,
        "base": manual_payload_from_event_json(base_snapshot),
        "candidate_after": manual_payload_from_event_json(candidate_after),
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
    user = load_user_or_raise(db, user_id=user_id)
    canonical_input = ensure_canonical_input_for_user(db=db, user_id=user_id)
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
    idempotent = base_existing_event is not None and event_json_equivalent(base_snapshot, candidate_after)
    if idempotent:
        return {
            "applied": True,
            "idempotent": True,
            "correction_change_id": None,
            "event_uid": resolved_event_uid,
            "rejected_pending_change_ids": [],
            "event": manual_payload_from_event_json(candidate_after),
        }

    now = datetime.now(timezone.utc)
    parsed_after = parse_after_json(resolved_event_uid, candidate_after)
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
        delta_seconds = safe_delta_seconds(before_json=base_snapshot, after_json=candidate_after)

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
        "event": manual_payload_from_event_json(candidate_after),
    }


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
        return event_row_to_json(event_row), event_row

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
        parsed = parse_after_json(event_uid, pending_row.after_json)
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
    next_title = coalesce_patch_text(title, fallback=str(base_snapshot.get("title") or "Untitled"), max_len=512)
    next_course_label = coalesce_patch_text(
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
    local_tz = resolve_timezone_name(timezone_name)
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


def load_user_or_raise(db: Session, *, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise ManualCorrectionNotFoundError("user not found")
    return user


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


def resolve_timezone_name(value: str | None) -> ZoneInfo:
    normalized = (value or "").strip() or "UTC"
    try:
        return ZoneInfo(normalized)
    except Exception:
        return ZoneInfo("UTC")


def coalesce_patch_text(value: str | None, *, fallback: str, max_len: int) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped[:max_len]
    fallback_clean = fallback.strip()
    if fallback_clean:
        return fallback_clean[:max_len]
    return "Unknown"[:max_len]


def list_pending_change_ids(*, db: Session, canonical_input_id: int, event_uid: str) -> list[int]:
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


def manual_payload_from_event_json(payload: dict) -> dict:
    start_raw = payload.get("start_at_utc")
    end_raw = payload.get("end_at_utc")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        raise ManualCorrectionValidationError("event payload missing start/end timestamps")
    start_at = parse_iso_datetime(start_raw)
    end_at = parse_iso_datetime(end_raw)
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


__all__ = [
    "ManualCorrectionNotFoundError",
    "ManualCorrectionValidationError",
    "apply_manual_correction",
    "preview_manual_correction",
]
