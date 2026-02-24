from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.db.models import (
    Change,
    ChangeType,
    EmailRuleCandidate,
    Event,
    Input,
    InputType,
    NotificationStatus,
    ReviewCandidateStatus,
    Snapshot,
)
from app.modules.notify.prefs_service import get_or_create_notification_prefs
from app.modules.notify.service import dispatch_notifications_for_changes, enqueue_notifications_for_changes
from app.modules.sync.email_rules import RULE_VERSION, evaluate_email_rule
from app.modules.sync.gmail_client import GmailMessageMetadata


class ReviewCandidateNotFoundError(RuntimeError):
    pass


class ReviewCandidateStateError(RuntimeError):
    pass


class ReviewCandidateApplyError(RuntimeError):
    pass


def list_review_candidates(
    db: Session,
    *,
    user_id: int,
    status: ReviewCandidateStatus | None,
    input_id: int | None,
    limit: int,
    offset: int,
) -> list[EmailRuleCandidate]:
    stmt = select(EmailRuleCandidate).where(EmailRuleCandidate.user_id == user_id)
    if status is not None:
        stmt = stmt.where(EmailRuleCandidate.status == status)
    if input_id is not None:
        stmt = stmt.where(EmailRuleCandidate.input_id == input_id)
    stmt = stmt.order_by(EmailRuleCandidate.created_at.desc(), EmailRuleCandidate.id.desc()).offset(offset).limit(limit)
    return db.scalars(stmt).all()


def create_rule_candidates_from_email_changes(
    db: Session,
    *,
    user_id: int,
    input_id: int,
    changes: Iterable[Change],
    message_by_id: dict[str, GmailMessageMetadata],
    timezone_name: str = "UTC",
) -> int:
    inserted = 0
    now = datetime.now(timezone.utc)
    for change in changes:
        if change.id is None:
            continue
        message = message_by_id.get(change.event_uid)
        if message is None:
            continue
        decision = evaluate_email_rule(
            subject=message.subject,
            snippet=message.snippet,
            from_header=message.from_header,
            internal_date=message.internal_date,
            timezone_name=timezone_name,
        )
        if not decision.actionable:
            continue
        insert_stmt = (
            pg_insert(EmailRuleCandidate)
            .values(
                user_id=user_id,
                input_id=input_id,
                gmail_message_id=message.message_id,
                source_change_id=change.id,
                status=ReviewCandidateStatus.PENDING.value,
                rule_version=RULE_VERSION,
                confidence=decision.confidence,
                proposed_event_type=decision.event_type,
                proposed_due_at=decision.due_at,
                proposed_title=decision.proposed_title,
                proposed_course_hint=decision.course_hint,
                reasons=decision.reasons,
                raw_extract=decision.raw_extract,
                subject=message.subject,
                from_header=message.from_header,
                snippet=message.snippet,
                applied_change_id=None,
                error=None,
                created_at=now,
                updated_at=now,
                applied_at=None,
                dismissed_at=None,
            )
            .on_conflict_do_nothing(
                constraint="uq_email_rule_candidates_input_message_rule",
            )
            .returning(EmailRuleCandidate.id)
        )
        candidate_id = db.execute(insert_stmt).scalar_one_or_none()
        if candidate_id is not None:
            inserted += 1
    return inserted


def apply_review_candidate(
    db: Session,
    *,
    user_id: int,
    candidate_id: int,
    target_input_id: int,
    target_event_uid: str,
    applied_due_at: datetime | None,
    note: str | None,
) -> tuple[EmailRuleCandidate, int, str | None]:
    now = datetime.now(timezone.utc)
    try:
        candidate = db.scalar(
            select(EmailRuleCandidate)
            .where(EmailRuleCandidate.id == candidate_id, EmailRuleCandidate.user_id == user_id)
            .with_for_update()
        )
        if candidate is None:
            raise ReviewCandidateNotFoundError("Review candidate not found")
        if candidate.status != ReviewCandidateStatus.PENDING:
            raise ReviewCandidateStateError("Review candidate is not pending")

        target_input = db.scalar(
            select(Input)
            .where(
                Input.id == target_input_id,
                Input.user_id == user_id,
                Input.type == InputType.ICS,
            )
            .with_for_update()
        )
        if target_input is None:
            raise ReviewCandidateApplyError("target_input_id must refer to an ICS input owned by current user")

        event = db.scalar(
            select(Event)
            .where(Event.input_id == target_input.id, Event.uid == target_event_uid)
            .with_for_update()
        )
        if event is None:
            raise ReviewCandidateApplyError("target_event_uid not found in target input")

        next_due = applied_due_at or candidate.proposed_due_at
        if next_due is None:
            raise ReviewCandidateApplyError("No due time available: pass applied_due_at or provide candidate proposed_due_at")
        if next_due.tzinfo is None:
            next_due = next_due.replace(tzinfo=timezone.utc)
        next_due_utc = next_due.astimezone(timezone.utc)

        prev_start = event.start_at_utc
        prev_end = event.end_at_utc
        duration = prev_end - prev_start
        if duration.total_seconds() <= 0:
            duration = datetime(1970, 1, 1, 1, 0, tzinfo=timezone.utc) - datetime(1970, 1, 1, 0, 0, tzinfo=timezone.utc)
        next_end = next_due_utc + duration

        previous_snapshot = db.scalar(
            select(Snapshot).where(Snapshot.input_id == target_input.id).order_by(Snapshot.id.desc()).limit(1)
        )
        event_count = int(db.scalar(select(func.count(Event.id)).where(Event.input_id == target_input.id)) or 0)
        raw_evidence_key = {
            "kind": "email_rule_apply",
            "candidate_id": candidate.id,
            "source_change_id": candidate.source_change_id,
            "note": note,
        }
        snapshot_hash = hashlib.sha256(
            f"email_rule_apply|{candidate.id}|{target_input.id}|{event.uid}|{next_due_utc.isoformat()}".encode("utf-8")
        ).hexdigest()
        after_snapshot = Snapshot(
            input_id=target_input.id,
            retrieved_at=now,
            etag=None,
            content_hash=snapshot_hash,
            event_count=event_count,
            raw_evidence_key=raw_evidence_key,
        )
        db.add(after_snapshot)
        db.flush()

        before_json = {
            "uid": event.uid,
            "course_label": event.course_label,
            "title": event.title,
            "start_at_utc": prev_start.isoformat(),
            "end_at_utc": prev_end.isoformat(),
        }

        if candidate.proposed_title:
            event.title = candidate.proposed_title
        if candidate.proposed_course_hint:
            event.course_label = candidate.proposed_course_hint
        event.start_at_utc = next_due_utc
        event.end_at_utc = next_end

        after_json = {
            "uid": event.uid,
            "course_label": event.course_label,
            "title": event.title,
            "start_at_utc": event.start_at_utc.isoformat(),
            "end_at_utc": event.end_at_utc.isoformat(),
        }
        change = Change(
            input_id=target_input.id,
            user_term_id=target_input.user_term_id,
            event_uid=event.uid,
            change_type=ChangeType.DUE_CHANGED,
            detected_at=now,
            before_json=before_json,
            after_json=after_json,
            delta_seconds=int((event.start_at_utc - prev_start).total_seconds()),
            before_snapshot_id=previous_snapshot.id if previous_snapshot is not None else None,
            after_snapshot_id=after_snapshot.id,
            evidence_keys={
                "before": previous_snapshot.raw_evidence_key if previous_snapshot is not None else None,
                "after": raw_evidence_key,
            },
        )
        db.add(change)
        db.flush()

        candidate.status = ReviewCandidateStatus.APPLIED
        candidate.applied_at = now
        candidate.dismissed_at = None
        candidate.applied_change_id = change.id
        candidate.error = None
        candidate.updated_at = now

        prefs = get_or_create_notification_prefs(db, user_id=user_id)
        notification_state: str | None = None
        if prefs.digest_enabled:
            enqueue_result = enqueue_notifications_for_changes(
                db,
                target_input,
                [change],
                deliver_after=now,
                enqueue_reason="digest_queue",
            )
            if enqueue_result.enqueued_count > 0:
                notification_state = "queued_for_digest"
            elif enqueue_result.dedup_skipped_count > 0:
                notification_state = "skipped_duplicate"
        else:
            dispatch_result = dispatch_notifications_for_changes(db, target_input, [change])
            notification_state = dispatch_result.notification_state

        db.commit()
        db.refresh(candidate)
        return candidate, change.id, notification_state
    except (ReviewCandidateNotFoundError, ReviewCandidateStateError, ReviewCandidateApplyError):
        raise
    except Exception as exc:
        db.rollback()
        _mark_candidate_failed(db, candidate_id=candidate_id, user_id=user_id, message=str(exc))
        raise ReviewCandidateApplyError("Failed to apply review candidate") from exc


def dismiss_review_candidate(
    db: Session,
    *,
    user_id: int,
    candidate_id: int,
    note: str | None,
) -> EmailRuleCandidate:
    candidate = db.scalar(
        select(EmailRuleCandidate)
        .where(EmailRuleCandidate.id == candidate_id, EmailRuleCandidate.user_id == user_id)
        .with_for_update()
    )
    if candidate is None:
        raise ReviewCandidateNotFoundError("Review candidate not found")
    if candidate.status != ReviewCandidateStatus.PENDING:
        raise ReviewCandidateStateError("Review candidate is not pending")

    now = datetime.now(timezone.utc)
    candidate.status = ReviewCandidateStatus.DISMISSED
    candidate.dismissed_at = now
    candidate.updated_at = now
    candidate.error = note.strip() if isinstance(note, str) and note.strip() else None
    db.commit()
    db.refresh(candidate)
    return candidate


def _mark_candidate_failed(db: Session, *, candidate_id: int, user_id: int, message: str) -> None:
    candidate = db.scalar(
        select(EmailRuleCandidate)
        .where(EmailRuleCandidate.id == candidate_id, EmailRuleCandidate.user_id == user_id)
        .with_for_update()
    )
    if candidate is None:
        return
    if candidate.status != ReviewCandidateStatus.PENDING:
        return
    now = datetime.now(timezone.utc)
    candidate.status = ReviewCandidateStatus.FAILED
    candidate.error = sanitize_log_message(message)[:512]
    candidate.updated_at = now
    db.commit()
