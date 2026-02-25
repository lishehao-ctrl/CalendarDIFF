from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.db.models import (
    Change,
    ChangeType,
    EmailActionItem,
    EmailMessage,
    EmailRoute,
    EmailRuleAnalysis,
    EmailRuleLabel,
    Event,
    Input,
    InputType,
    Notification,
    NotificationChannel,
    NotificationStatus,
    Snapshot,
)
from app.modules.notify.prefs_service import get_or_create_notification_prefs
from app.modules.notify.service import enqueue_notifications_for_changes
from app.modules.sync.email_rules import ACTIONABLE_EVENT_TYPES, RULE_VERSION, evaluate_email_rule
from app.modules.sync.gmail_client import GmailMessageMetadata
from app.modules.users.service import get_single_ics_input_for_user


class EmailQueueItemNotFoundError(RuntimeError):
    pass


class EmailQueueStateError(RuntimeError):
    pass


class EmailQueueApplyError(RuntimeError):
    pass


def create_review_queue_from_email_changes(
    db: Session,
    *,
    user_id: int,
    input_id: int,
    changes: Iterable[Change],
    message_by_id: dict[str, GmailMessageMetadata],
    timezone_name: str = "UTC",
) -> int:
    del input_id
    inserted = 0
    now = datetime.now(timezone.utc)
    event_keys = sorted(ACTIONABLE_EVENT_TYPES | {"announcement", "grade", "other"})

    for change in changes:
        message_id = getattr(change, "event_uid", None)
        if not isinstance(message_id, str) or not message_id:
            continue
        metadata = message_by_id.get(message_id)
        if metadata is None:
            continue

        decision = evaluate_email_rule(
            subject=metadata.subject,
            snippet=metadata.snippet,
            from_header=metadata.from_header,
            internal_date=metadata.internal_date,
            timezone_name=timezone_name,
        )
        if not decision.actionable:
            continue

        email_row = db.get(EmailMessage, metadata.message_id)
        evidence_key = (
            change.evidence_keys.get("after")
            if isinstance(getattr(change, "evidence_keys", None), dict)
            and isinstance(change.evidence_keys.get("after"), dict)
            else {"kind": "gmail", "message_id": metadata.message_id}
        )
        if email_row is None:
            email_row = EmailMessage(
                email_id=metadata.message_id,
                user_id=user_id,
                from_addr=metadata.from_header,
                subject=metadata.subject,
                date_rfc822=metadata.internal_date,
                received_at=now,
                evidence_key=evidence_key,
            )
            db.add(email_row)
            inserted += 1
        else:
            email_row.user_id = user_id
            email_row.from_addr = metadata.from_header
            email_row.subject = metadata.subject
            email_row.date_rfc822 = metadata.internal_date
            email_row.evidence_key = evidence_key

        label_row = db.get(EmailRuleLabel, metadata.message_id)
        if label_row is None:
            label_row = EmailRuleLabel(email_id=metadata.message_id)
            db.add(label_row)
        label_row.label = decision.label
        label_row.confidence = float(decision.confidence)
        label_row.reasons = list(decision.reasons)[:3]
        label_row.course_hints = [decision.course_hint] if decision.course_hint else []
        label_row.event_type = decision.event_type
        label_row.raw_extract = {
            "deadline_text": decision.raw_extract.get("deadline_text"),
            "time_text": decision.raw_extract.get("time_text"),
            "location_text": decision.raw_extract.get("location_text"),
        }
        label_row.notes = None

        db.query(EmailActionItem).filter(EmailActionItem.email_id == metadata.message_id).delete(synchronize_session=False)
        db.add(
            EmailActionItem(
                email_id=metadata.message_id,
                action=f"Review {decision.event_type or 'timeline'} update",
                due_iso=decision.due_at.isoformat() if decision.due_at is not None else None,
                where_text=decision.raw_extract.get("location_text"),
            )
        )

        analysis_row = db.get(EmailRuleAnalysis, metadata.message_id)
        if analysis_row is None:
            analysis_row = EmailRuleAnalysis(email_id=metadata.message_id)
            db.add(analysis_row)
        analysis_row.event_flags = {key: key == decision.event_type for key in event_keys}
        snippet_text = (metadata.snippet or metadata.subject or "").strip()
        analysis_row.matched_snippets = (
            [{"rule": decision.event_type or "actionable", "snippet": snippet_text[:240]}] if snippet_text else []
        )
        analysis_row.drop_reason_codes = []

        route_row = db.get(EmailRoute, metadata.message_id)
        if route_row is None:
            route_row = EmailRoute(
                email_id=metadata.message_id,
                route="review",
                routed_at=now,
                viewed_at=None,
                notified_at=None,
            )
            db.add(route_row)
            inserted += 1
        elif route_row.route == "review":
            route_row.routed_at = now

    return inserted


def list_email_queue(
    db: Session,
    *,
    user_id: int,
    route: str | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(EmailMessage, EmailRuleLabel, EmailRuleAnalysis, EmailRoute)
        .join(EmailRoute, EmailRoute.email_id == EmailMessage.email_id)
        .outerjoin(EmailRuleLabel, EmailRuleLabel.email_id == EmailMessage.email_id)
        .outerjoin(EmailRuleAnalysis, EmailRuleAnalysis.email_id == EmailMessage.email_id)
        .where(EmailMessage.user_id == user_id)
    )
    if route is not None:
        stmt = stmt.where(EmailRoute.route == route)

    rows = db.execute(
        stmt.order_by(EmailRoute.routed_at.desc(), EmailMessage.received_at.desc(), EmailMessage.email_id.asc())
        .offset(offset)
        .limit(limit)
    ).all()
    email_ids = [message.email_id for message, _, _, _ in rows]
    action_items_by_email = _load_action_items_by_email(db, email_ids=email_ids)

    items: list[dict[str, Any]] = []
    for message, label, analysis, route_row in rows:
        matched_snippets = _normalize_matched_snippets(analysis.matched_snippets if analysis is not None else None)
        item = {
            "email_id": message.email_id,
            "from_addr": message.from_addr,
            "subject": message.subject,
            "date_rfc822": message.date_rfc822,
            "route": route_row.route,
            "event_type": label.event_type if label is not None else None,
            "confidence": float(label.confidence) if label is not None else 0.0,
            "reasons": _as_string_list(label.reasons if label is not None else []),
            "course_hints": _as_string_list(label.course_hints if label is not None else []),
            "action_items": action_items_by_email.get(message.email_id, []),
            "rule_analysis": {
                "event_flags": _as_bool_map(analysis.event_flags if analysis is not None else {}),
                "matched_snippets": matched_snippets,
                "drop_reason_codes": _as_string_list(analysis.drop_reason_codes if analysis is not None else []),
            },
            "flags": {
                "viewed": route_row.viewed_at is not None,
                "notified": route_row.notified_at is not None,
                "viewed_at": route_row.viewed_at,
                "notified_at": route_row.notified_at,
            },
        }
        items.append(item)
    return items


def update_email_route(
    db: Session,
    *,
    user_id: int,
    email_id: str,
    route: str,
) -> EmailRoute:
    now = datetime.now(timezone.utc)
    route_row = db.scalar(
        select(EmailRoute)
        .join(EmailMessage, EmailMessage.email_id == EmailRoute.email_id)
        .where(EmailRoute.email_id == email_id, EmailMessage.user_id == user_id)
        .with_for_update()
    )
    if route_row is None:
        raise EmailQueueItemNotFoundError("Email queue item not found")

    message = db.scalar(
        select(EmailMessage)
        .where(EmailMessage.email_id == email_id, EmailMessage.user_id == user_id)
        .with_for_update()
    )
    if message is None:
        raise EmailQueueItemNotFoundError("Email message not found")

    previous_route = route_row.route
    if previous_route != route:
        route_row.route = route
        route_row.routed_at = now

    if route == "notify":
        _handle_notify_route_side_effect(db, user_id=user_id, message=message, route_row=route_row, now=now)
    elif previous_route == "notify" and route != "notify":
        _cancel_pending_notify_side_effect(db, user_id=user_id, email_id=email_id, now=now)

    db.commit()
    db.refresh(route_row)
    return route_row


def mark_email_viewed(
    db: Session,
    *,
    user_id: int,
    email_id: str,
) -> EmailRoute:
    route_row = db.scalar(
        select(EmailRoute)
        .join(EmailMessage, EmailMessage.email_id == EmailRoute.email_id)
        .where(EmailRoute.email_id == email_id, EmailMessage.user_id == user_id)
        .with_for_update()
    )
    if route_row is None:
        raise EmailQueueItemNotFoundError("Email queue item not found")
    route_row.viewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(route_row)
    return route_row


def apply_email_review(
    db: Session,
    *,
    user_id: int,
    email_id: str,
    mode: str,
    target_event_uid: str | None,
    applied_due_at: datetime | None,
    note: str | None,
) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    route_row = db.scalar(
        select(EmailRoute)
        .join(EmailMessage, EmailMessage.email_id == EmailRoute.email_id)
        .where(EmailRoute.email_id == email_id, EmailMessage.user_id == user_id)
        .with_for_update()
    )
    if route_row is None:
        raise EmailQueueItemNotFoundError("Email queue item not found")
    if route_row.route != "review":
        raise EmailQueueStateError("apply is allowed only when route=review")

    message = db.scalar(
        select(EmailMessage)
        .where(EmailMessage.email_id == email_id, EmailMessage.user_id == user_id)
        .with_for_update()
    )
    if message is None:
        raise EmailQueueItemNotFoundError("Email message not found")

    label = db.scalar(select(EmailRuleLabel).where(EmailRuleLabel.email_id == email_id))
    action_items = db.scalars(
        select(EmailActionItem).where(EmailActionItem.email_id == email_id).order_by(EmailActionItem.id.asc())
    ).all()
    due_at = (
        _as_utc(applied_due_at)
        if applied_due_at is not None
        else _resolve_due_at(action_items=action_items, raw_extract=label.raw_extract if label is not None else None)
    )
    if due_at is None:
        raise EmailQueueApplyError("No parseable due/time; keep in review")

    if mode == "create_new":
        task_id, change_id = _apply_email_create_new(
            db,
            user_id=user_id,
            message=message,
            label=label,
            action_items=action_items,
            route_row=route_row,
            note=note,
            due_at=due_at,
            now=now,
        )
        db.commit()
        return task_id, change_id

    if mode == "update_existing":
        task_id, change_id = _apply_email_update_existing(
            db,
            user_id=user_id,
            message=message,
            route_row=route_row,
            target_event_uid=target_event_uid,
            note=note,
            due_at=due_at,
            now=now,
        )
        db.commit()
        return task_id, change_id

    raise EmailQueueApplyError("Unsupported apply mode")


def _apply_email_create_new(
    db: Session,
    *,
    user_id: int,
    message: EmailMessage,
    label: EmailRuleLabel | None,
    action_items: list[EmailActionItem],
    route_row: EmailRoute,
    note: str | None,
    due_at: datetime,
    now: datetime,
) -> tuple[int, int]:
    target_input = _select_apply_target_ics_input(db, user_id=user_id)
    if target_input is None:
        raise EmailQueueStateError("No active ICS input is available for apply")

    event_uid = f"email-apply:{message.email_id}"
    existing_event = db.scalar(select(Event).where(Event.input_id == target_input.id, Event.uid == event_uid).limit(1))
    if existing_event is not None:
        raise EmailQueueStateError("Email already applied to canonical schedule")

    subject = (message.subject or "").strip()
    title_base = subject if subject else message.email_id
    title = f"[EMAIL] {title_base}"[:512]

    course_hints = _as_string_list(label.course_hints if label is not None else [])
    course_label = (course_hints[0] if course_hints else "Unknown")[:64]
    where_text = _resolve_where_text(action_items=action_items, raw_extract=label.raw_extract if label is not None else None)

    event = Event(
        input_id=target_input.id,
        uid=event_uid,
        course_label=course_label,
        title=title,
        start_at_utc=due_at,
        end_at_utc=due_at + timedelta(hours=1),
    )
    db.add(event)
    db.flush()

    previous_snapshot = db.scalar(
        select(Snapshot).where(Snapshot.input_id == target_input.id).order_by(Snapshot.id.desc()).limit(1)
    )
    snapshot = _create_apply_snapshot(
        db,
        input_id=target_input.id,
        now=now,
        note=note,
        payload_key=f"email-apply|{message.email_id}|{target_input.id}|{due_at.isoformat()}",
        evidence_kind="email_review_apply",
        evidence_ref_id=message.email_id,
    )

    evidence_ref = message.evidence_key if isinstance(message.evidence_key, dict) else {"kind": "email", "email_id": message.email_id}
    after_json = {
        "uid": event.uid,
        "title": event.title,
        "course_label": event.course_label,
        "start_at_utc": event.start_at_utc.isoformat(),
        "end_at_utc": event.end_at_utc.isoformat(),
        "due_at": event.start_at_utc.isoformat(),
        "where": where_text,
        "email_id": message.email_id,
        "input_kind": "email_review_apply",
    }
    change = Change(
        input_id=target_input.id,
        event_uid=event.uid,
        change_type=ChangeType.CREATED,
        detected_at=now,
        before_json=None,
        after_json=after_json,
        delta_seconds=None,
        before_snapshot_id=previous_snapshot.id if previous_snapshot is not None else None,
        after_snapshot_id=snapshot.id,
        evidence_keys={"after": evidence_ref, "input_ref": {"kind": "email", "email_id": message.email_id}},
    )
    db.add(change)
    db.flush()

    _enqueue_change_notification_if_enabled(db, user_id=user_id, input_row=target_input, change=change, now=now)
    _mark_route_archived(route_row, now=now)
    return event.id, change.id


def _apply_email_update_existing(
    db: Session,
    *,
    user_id: int,
    message: EmailMessage,
    route_row: EmailRoute,
    target_event_uid: str | None,
    note: str | None,
    due_at: datetime,
    now: datetime,
) -> tuple[int, int]:
    if target_event_uid is None or not target_event_uid.strip():
        raise EmailQueueApplyError("target_event_uid is required for mode=update_existing")

    target_input = _select_apply_target_ics_input(db, user_id=user_id)
    if target_input is None:
        raise EmailQueueApplyError("No active ICS input is available for apply")

    event = db.scalar(
        select(Event)
        .where(Event.input_id == target_input.id, Event.uid == target_event_uid.strip())
        .with_for_update()
        .limit(1)
    )
    if event is None:
        raise EmailQueueApplyError("target_event_uid not found in target input")

    prev_start = _as_utc(event.start_at_utc)
    prev_end = _as_utc(event.end_at_utc)
    duration = prev_end - prev_start
    if duration.total_seconds() <= 0:
        duration = timedelta(hours=1)

    next_due_utc = _as_utc(due_at)
    next_end_utc = next_due_utc + duration
    previous_snapshot = db.scalar(
        select(Snapshot).where(Snapshot.input_id == target_input.id).order_by(Snapshot.id.desc()).limit(1)
    )
    snapshot = _create_apply_snapshot(
        db,
        input_id=target_input.id,
        now=now,
        note=note,
        payload_key=f"email-update|{message.email_id}|{target_input.id}|{event.uid}|{next_due_utc.isoformat()}",
        evidence_kind="email_review_update_existing",
        evidence_ref_id=message.email_id,
    )

    before_json = {
        "uid": event.uid,
        "course_label": event.course_label,
        "title": event.title,
        "start_at_utc": prev_start.isoformat(),
        "end_at_utc": prev_end.isoformat(),
    }
    event.start_at_utc = next_due_utc
    event.end_at_utc = next_end_utc
    after_json = {
        "uid": event.uid,
        "course_label": event.course_label,
        "title": event.title,
        "start_at_utc": event.start_at_utc.isoformat(),
        "end_at_utc": event.end_at_utc.isoformat(),
        "due_at": event.start_at_utc.isoformat(),
        "email_id": message.email_id,
        "input_kind": "email_review_update_existing",
    }
    evidence_ref = message.evidence_key if isinstance(message.evidence_key, dict) else {"kind": "email", "email_id": message.email_id}
    change = Change(
        input_id=target_input.id,
        event_uid=event.uid,
        change_type=ChangeType.DUE_CHANGED,
        detected_at=now,
        before_json=before_json,
        after_json=after_json,
        delta_seconds=int((event.start_at_utc - prev_start).total_seconds()),
        before_snapshot_id=previous_snapshot.id if previous_snapshot is not None else None,
        after_snapshot_id=snapshot.id,
        evidence_keys={"before": previous_snapshot.raw_evidence_key if previous_snapshot is not None else None, "after": evidence_ref},
    )
    db.add(change)
    db.flush()

    _enqueue_change_notification_if_enabled(db, user_id=user_id, input_row=target_input, change=change, now=now)
    _mark_route_archived(route_row, now=now)
    return event.id, change.id


def _create_apply_snapshot(
    db: Session,
    *,
    input_id: int,
    now: datetime,
    note: str | None,
    payload_key: str,
    evidence_kind: str,
    evidence_ref_id: str,
) -> Snapshot:
    event_count = int(db.scalar(select(func.count(Event.id)).where(Event.input_id == input_id)) or 0)
    raw_evidence_key = {"kind": evidence_kind, "email_id": evidence_ref_id, "note": note}
    snapshot = Snapshot(
        input_id=input_id,
        retrieved_at=now,
        etag=None,
        content_hash=hashlib.sha256(payload_key.encode("utf-8")).hexdigest(),
        event_count=event_count,
        raw_evidence_key=raw_evidence_key,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _enqueue_change_notification_if_enabled(
    db: Session,
    *,
    user_id: int,
    input_row: Input,
    change: Change,
    now: datetime,
) -> None:
    prefs = get_or_create_notification_prefs(db, user_id=user_id)
    if prefs.digest_enabled:
        enqueue_notifications_for_changes(
            db,
            input_row,
            [change],
            deliver_after=now,
            enqueue_reason="digest_queue",
        )


def _mark_route_archived(route_row: EmailRoute, *, now: datetime) -> None:
    route_row.route = "archive"
    route_row.routed_at = now
    route_row.viewed_at = now


def _load_action_items_by_email(db: Session, *, email_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not email_ids:
        return {}
    rows = db.scalars(
        select(EmailActionItem)
        .where(EmailActionItem.email_id.in_(email_ids))
        .order_by(EmailActionItem.email_id.asc(), EmailActionItem.id.asc())
    ).all()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row.email_id].append(
            {
                "action": row.action,
                "due_iso": row.due_iso,
                "where": row.where_text,
            }
        )
    return grouped


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        stripped = item.strip()
        if not stripped:
            continue
        out.append(stripped)
    return out


def _as_bool_map(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, bool] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        out[key] = bool(item)
    return out


def _normalize_matched_snippets(value: Any) -> list[dict[str, str]]:
    if isinstance(value, dict):
        out: list[dict[str, str]] = []
        for key, snippet in value.items():
            if isinstance(key, str) and isinstance(snippet, str) and snippet.strip():
                out.append({"rule": key, "snippet": snippet.strip()[:240]})
        return out
    if isinstance(value, list):
        out = []
        for row in value:
            if not isinstance(row, dict):
                continue
            rule = row.get("rule")
            snippet = row.get("snippet")
            if isinstance(rule, str) and isinstance(snippet, str) and snippet.strip():
                out.append({"rule": rule.strip(), "snippet": snippet.strip()[:240]})
        return out
    return []


def _parse_maybe_datetime(value: str | None) -> datetime | None:
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
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resolve_due_at(*, action_items: list[EmailActionItem], raw_extract: dict | None) -> datetime | None:
    for row in action_items:
        parsed = _parse_maybe_datetime(row.due_iso)
        if parsed is not None:
            return parsed
    if isinstance(raw_extract, dict):
        for key in ("time_text", "deadline_text"):
            parsed = _parse_maybe_datetime(raw_extract.get(key))
            if parsed is not None:
                return parsed
    return None


def _resolve_where_text(*, action_items: list[EmailActionItem], raw_extract: dict | None) -> str | None:
    for row in action_items:
        value = (row.where_text or "").strip()
        if value:
            return value
    if isinstance(raw_extract, dict):
        location = raw_extract.get("location_text")
        if isinstance(location, str):
            stripped = location.strip()
            if stripped:
                return stripped
    return None


def _select_apply_target_ics_input(db: Session, *, user_id: int) -> Input | None:
    return get_single_ics_input_for_user(
        db,
        user_id=user_id,
        require_active=True,
        for_update=True,
    )


def _select_notify_target_input(db: Session, *, user_id: int) -> Input | None:
    input_row = db.scalar(
        select(Input)
        .where(
            Input.user_id == user_id,
            Input.type == InputType.EMAIL,
            Input.is_active.is_(True),
        )
        .order_by(Input.created_at.asc(), Input.id.asc())
        .limit(1)
    )
    if input_row is not None:
        return input_row
    return get_single_ics_input_for_user(
        db,
        user_id=user_id,
        require_active=True,
        for_update=False,
    )


def _handle_notify_route_side_effect(
    db: Session,
    *,
    user_id: int,
    message: EmailMessage,
    route_row: EmailRoute,
    now: datetime,
) -> None:
    target_input = _select_notify_target_input(db, user_id=user_id)
    if target_input is None:
        raise EmailQueueStateError("No active input available for notify route")

    change = _get_or_create_notify_change(
        db,
        message=message,
        target_input=target_input,
        detected_at=now,
    )
    prefs = get_or_create_notification_prefs(db, user_id=user_id)
    if not prefs.digest_enabled:
        return

    enqueue_result = enqueue_notifications_for_changes(
        db,
        target_input,
        [change],
        deliver_after=now,
        enqueue_reason="digest_queue",
    )
    if enqueue_result.enqueued_count > 0 or enqueue_result.dedup_skipped_count > 0:
        route_row.notified_at = now


def _get_or_create_notify_change(
    db: Session,
    *,
    message: EmailMessage,
    target_input: Input,
    detected_at: datetime,
) -> Change:
    event_uid = f"email-route:{message.email_id}"
    existing = db.scalar(
        select(Change)
        .where(Change.input_id == target_input.id, Change.event_uid == event_uid)
        .order_by(Change.id.desc())
        .limit(1)
    )
    if existing is not None:
        return existing

    label = db.scalar(select(EmailRuleLabel).where(EmailRuleLabel.email_id == message.email_id))
    course_hints = _as_string_list(label.course_hints if label is not None else [])
    course_label = course_hints[0] if course_hints else "Unknown"
    title = (message.subject or message.email_id).strip() or message.email_id

    event_count = int(db.scalar(select(func.count(Event.id)).where(Event.input_id == target_input.id)) or 0)
    snapshot_hash = hashlib.sha256(
        f"email-route-notify|{message.email_id}|{target_input.id}|{detected_at.isoformat()}".encode("utf-8")
    ).hexdigest()
    snapshot = Snapshot(
        input_id=target_input.id,
        retrieved_at=detected_at,
        etag=None,
        content_hash=snapshot_hash,
        event_count=event_count,
        raw_evidence_key={"kind": "email_route_notify", "email_id": message.email_id},
    )
    db.add(snapshot)
    db.flush()

    evidence_ref = message.evidence_key if isinstance(message.evidence_key, dict) else {"kind": "email", "email_id": message.email_id}
    change = Change(
        input_id=target_input.id,
        event_uid=event_uid,
        change_type=ChangeType.CREATED,
        detected_at=detected_at,
        before_json=None,
        after_json={
            "title": title[:512],
            "course_label": course_label[:64],
            "subject": message.subject,
            "from": message.from_addr,
            "date": message.date_rfc822,
            "email_id": message.email_id,
            "input_kind": "email_route_notify",
        },
        delta_seconds=None,
        before_snapshot_id=None,
        after_snapshot_id=snapshot.id,
        evidence_keys={"after": evidence_ref},
    )
    db.add(change)
    db.flush()
    return change


def _cancel_pending_notify_side_effect(
    db: Session,
    *,
    user_id: int,
    email_id: str,
    now: datetime,
) -> None:
    event_uid = f"email-route:{email_id}"
    change_ids = db.scalars(
        select(Change.id)
        .join(Input, Input.id == Change.input_id)
        .where(Input.user_id == user_id, Change.event_uid == event_uid)
    ).all()
    if not change_ids:
        return

    notifications = db.scalars(
        select(Notification).where(
            Notification.change_id.in_(change_ids),
            Notification.channel == NotificationChannel.EMAIL,
            Notification.status == NotificationStatus.PENDING,
        )
    ).all()
    for row in notifications:
        row.status = NotificationStatus.FAILED
        row.error = sanitize_log_message("email route moved away from notify before send")
        row.sent_at = None
        row.notified_at = now
