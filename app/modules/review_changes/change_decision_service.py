from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.db.models import Change, ChangeType, Event, Input, IntegrationOutbox, OutboxStatus, ReviewStatus


class ReviewChangeNotFoundError(RuntimeError):
    pass


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
        apply_change_to_canonical_event(db=db, change=row)
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


def apply_change_to_canonical_event(*, db: Session, change: Change) -> None:
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

    parsed = parse_after_json(change.event_uid, after_json)
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


def parse_after_json(event_uid: str, payload: dict) -> dict | None:
    del event_uid
    start_raw = payload.get("start_at_utc")
    end_raw = payload.get("end_at_utc")
    title_raw = payload.get("title")
    course_label_raw = payload.get("course_label")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        return None
    start_at = parse_iso_datetime(start_raw)
    end_at = parse_iso_datetime(end_raw)
    if start_at is None or end_at is None or end_at <= start_at:
        return None
    title = title_raw.strip()[:512] if isinstance(title_raw, str) and title_raw.strip() else "Untitled"
    course_label = (
        course_label_raw.strip()[:64]
        if isinstance(course_label_raw, str) and course_label_raw.strip()
        else "Unknown"
    )
    return {
        "title": title,
        "course_label": course_label,
        "start_at_utc": start_at,
        "end_at_utc": end_at,
    }


def parse_iso_datetime(value: str) -> datetime | None:
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


def event_json_equivalent(before_json: dict, after_json: dict) -> bool:
    return (
        str(before_json.get("title") or "") == str(after_json.get("title") or "")
        and str(before_json.get("course_label") or "") == str(after_json.get("course_label") or "")
        and str(before_json.get("start_at_utc") or "") == str(after_json.get("start_at_utc") or "")
        and str(before_json.get("end_at_utc") or "") == str(after_json.get("end_at_utc") or "")
    )


def safe_delta_seconds(*, before_json: dict, after_json: dict) -> int | None:
    before_raw = before_json.get("start_at_utc")
    after_raw = after_json.get("start_at_utc")
    if not isinstance(before_raw, str) or not isinstance(after_raw, str):
        return None
    before = parse_iso_datetime(before_raw)
    after = parse_iso_datetime(after_raw)
    if before is None or after is None:
        return None
    return int((after - before).total_seconds())


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def event_row_to_json(event: Event) -> dict:
    return {
        "uid": event.uid,
        "title": event.title,
        "course_label": event.course_label,
        "start_at_utc": as_utc(event.start_at_utc).isoformat(),
        "end_at_utc": as_utc(event.end_at_utc).isoformat(),
    }


__all__ = [
    "ReviewChangeNotFoundError",
    "apply_change_to_canonical_event",
    "decide_review_change",
    "event_json_equivalent",
    "event_row_to_json",
    "mark_review_change_viewed",
    "parse_after_json",
    "parse_iso_datetime",
    "safe_delta_seconds",
]
