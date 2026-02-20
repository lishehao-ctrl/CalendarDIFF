from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.core.security import decrypt_secret
from app.db.models import Change, Event, Snapshot, SnapshotEvent, Source
from app.modules.diff.engine import EventState, compute_diff
from app.modules.evidence.store import save_ics
from app.modules.notify.interface import Notifier
from app.modules.notify.service import dispatch_notifications_for_changes
from app.modules.sync.ics_client import ICSClient
from app.modules.sync.ics_parser import ICSParser
from app.modules.sync.normalizer import normalize_events

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncRunResult:
    source_id: int
    changes_created: int
    email_sent: bool
    last_error: str | None


def list_due_sources(db: Session, now: datetime | None = None) -> list[Source]:
    current = now or datetime.now(timezone.utc)
    active_sources = db.scalars(select(Source).where(Source.is_active.is_(True))).all()

    due_sources: list[Source] = []
    for source in active_sources:
        if source.last_checked_at is None:
            due_sources.append(source)
            continue

        checked_at = _as_utc(source.last_checked_at)
        elapsed = current - checked_at
        if elapsed >= timedelta(minutes=source.interval_minutes):
            due_sources.append(source)

    return due_sources


def sync_source(
    db: Session,
    source: Source,
    notifier: Notifier | None = None,
    ics_client: ICSClient | None = None,
    ics_parser: ICSParser | None = None,
) -> SyncRunResult:
    settings = get_settings()
    run_started_at = datetime.now(timezone.utc)
    source.last_checked_at = run_started_at
    source.last_error = None

    client = ics_client or ICSClient()
    parser = ics_parser or ICSParser()

    try:
        source_url = decrypt_secret(source.encrypted_url)
        fetched = client.fetch(source_url, source_id=source.id)
        evidence_key = save_ics(source_id=source.id, content=fetched.content, retrieved_at=fetched.fetched_at_utc)
        raw_events = parser.parse(fetched.content)
        normalized_events = normalize_events(raw_events)
    except Exception as exc:
        return _handle_source_error(db, source, exc)

    try:
        snapshot = Snapshot(
            source_id=source.id,
            retrieved_at=fetched.fetched_at_utc,
            etag=fetched.etag,
            content_hash=hashlib.sha256(fetched.content).hexdigest(),
            event_count=len(normalized_events),
            raw_evidence_key=evidence_key,
        )
        db.add(snapshot)
        db.flush()

        previous_snapshot = _get_previous_snapshot(db, source_id=source.id, current_snapshot_id=snapshot.id)

        for event in normalized_events:
            db.add(
                SnapshotEvent(
                    snapshot_id=snapshot.id,
                    uid=event.uid,
                    course_label=event.course_label,
                    title=event.title,
                    start_at_utc=event.start_at_utc,
                    end_at_utc=event.end_at_utc,
                )
            )

        canonical_rows = db.scalars(select(Event).where(Event.source_id == source.id)).all()
        canonical_map: dict[str, EventState] = {
            row.uid: EventState(
                uid=row.uid,
                course_label=row.course_label,
                title=row.title,
                start_at_utc=_as_utc(row.start_at_utc),
                end_at_utc=_as_utc(row.end_at_utc),
            )
            for row in canonical_rows
        }
        snapshot_map = {event.uid: event for event in normalized_events}

        candidate_removed = set(canonical_map) - set(snapshot_map)
        debounced_removed_uids = _find_debounced_removed_uids(db, source_id=source.id, candidate_uids=candidate_removed)

        diff_result = compute_diff(
            canonical_events=canonical_map,
            snapshot_events=snapshot_map,
            debounced_removed_uids=debounced_removed_uids,
        )

        canonical_by_uid = {row.uid: row for row in canonical_rows}

        for created in diff_result.created_events:
            db.add(
                Event(
                    source_id=source.id,
                    uid=created.uid,
                    course_label=created.course_label,
                    title=created.title,
                    start_at_utc=created.start_at_utc,
                    end_at_utc=created.end_at_utc,
                )
            )

        for updated in diff_result.updated_events:
            row = canonical_by_uid.get(updated.uid)
            if row is None:
                continue
            row.course_label = updated.course_label
            row.title = updated.title
            row.start_at_utc = updated.start_at_utc
            row.end_at_utc = updated.end_at_utc

        for removed_uid in diff_result.removed_uids:
            row = canonical_by_uid.get(removed_uid)
            if row is not None:
                db.delete(row)

        change_rows: list[Change] = []
        detected_at = datetime.now(timezone.utc)
        for payload in diff_result.changes:
            change = Change(
                source_id=source.id,
                event_uid=payload.event_uid,
                change_type=payload.change_type,
                detected_at=detected_at,
                before_json=payload.before_json,
                after_json=payload.after_json,
                delta_seconds=payload.delta_seconds,
                before_snapshot_id=previous_snapshot.id if previous_snapshot is not None else None,
                after_snapshot_id=snapshot.id,
                evidence_keys={
                    "before": previous_snapshot.raw_evidence_key if previous_snapshot is not None else None,
                    "after": snapshot.raw_evidence_key,
                },
            )
            db.add(change)
            change_rows.append(change)

        db.flush()

        email_sent = False
        notify_error: str | None = None
        if settings.enable_notifications:
            notify_result = dispatch_notifications_for_changes(
                db=db,
                source=source,
                changes=change_rows,
                notifier=notifier,
            )
            email_sent = notify_result.email_sent
            notify_error = notify_result.error

        source.last_checked_at = datetime.now(timezone.utc)
        source.last_error = None

        db.commit()
        return SyncRunResult(
            source_id=source.id,
            changes_created=len(change_rows),
            email_sent=email_sent,
            last_error=notify_error,
        )
    except Exception as exc:
        return _handle_source_error(db, source, exc)


def _find_debounced_removed_uids(db: Session, source_id: int, candidate_uids: set[str]) -> set[str]:
    if not candidate_uids:
        return set()

    snapshot_id_stmt: Select[tuple[int]] = (
        select(Snapshot.id)
        .where(Snapshot.source_id == source_id)
        .order_by(Snapshot.id.desc())
        .limit(3)
    )
    latest_snapshot_ids = db.scalars(snapshot_id_stmt).all()
    if len(latest_snapshot_ids) < 3:
        return set()

    present_uid_stmt = select(SnapshotEvent.uid).where(
        SnapshotEvent.snapshot_id.in_(latest_snapshot_ids),
        SnapshotEvent.uid.in_(candidate_uids),
    )
    present_uids = set(db.scalars(present_uid_stmt).all())

    return candidate_uids - present_uids


def _get_previous_snapshot(db: Session, source_id: int, current_snapshot_id: int) -> Snapshot | None:
    stmt = (
        select(Snapshot)
        .where(
            Snapshot.source_id == source_id,
            Snapshot.id < current_snapshot_id,
        )
        .order_by(Snapshot.id.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def _handle_source_error(db: Session, source: Source, exc: Exception) -> SyncRunResult:
    db.rollback()

    safe_error = sanitize_log_message(str(exc))
    logger.error("sync failed for source_id=%s error=%s", source.id, safe_error)

    source_in_db = db.get(Source, source.id)
    if source_in_db is None:
        return SyncRunResult(source_id=source.id, changes_created=0, email_sent=False, last_error=safe_error)

    source_in_db.last_checked_at = datetime.now(timezone.utc)
    source_in_db.last_error = safe_error
    db.commit()

    return SyncRunResult(source_id=source.id, changes_created=0, email_sent=False, last_error=safe_error)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
