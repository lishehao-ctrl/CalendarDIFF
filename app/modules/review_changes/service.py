from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Change, ChangeType, Event, Input, ReviewStatus


class ReviewChangeNotFoundError(RuntimeError):
    pass


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
        select(Change)
        .join(Input, Input.id == Change.input_id)
        .where(Input.user_id == user_id)
        .order_by(Change.detected_at.desc(), Change.id.desc())
        .offset(0)
        .limit(limit + offset + 512)
    )

    if review_status == "pending":
        stmt = stmt.where(Change.review_status == ReviewStatus.PENDING)
    elif review_status == "approved":
        stmt = stmt.where(Change.review_status == ReviewStatus.APPROVED)
    elif review_status == "rejected":
        stmt = stmt.where(Change.review_status == ReviewStatus.REJECTED)

    rows = db.scalars(stmt).all()

    output: list[dict] = []
    for row in rows:
        sources = _parse_sources(row.proposal_sources_json)
        primary_source_id = sources[0]["source_id"] if sources else None
        if source_id is not None and source_id not in {item["source_id"] for item in sources if isinstance(item.get("source_id"), int)}:
            continue
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
                "source_id": primary_source_id,
                "viewed_at": row.viewed_at,
                "viewed_note": row.viewed_note,
                "reviewed_at": row.reviewed_at,
                "review_note": row.review_note,
            }
        )

    return output[offset : offset + limit]


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

    db.commit()
    db.refresh(row)
    return row, False


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
