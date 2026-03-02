from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    EmailActionItem,
    EmailMessage,
    EmailRoute,
    EmailRuleAnalysis,
    EmailRuleLabel,
)
from app.modules.sync.email_rules import ACTIONABLE_EVENT_TYPES, EmailRuleDecision, evaluate_email_rule
from app.modules.sync.gmail_client import GmailMessageMetadata


class EmailQueueItemNotFoundError(RuntimeError):
    pass


def create_review_queue_from_email_changes(
    db: Session,
    *,
    user_id: int,
    messages: Iterable[GmailMessageMetadata],
    timezone_name: str = "UTC",
) -> int:
    actionable_count = 0
    now = datetime.now(timezone.utc)
    event_keys = sorted(ACTIONABLE_EVENT_TYPES | {"announcement", "grade", "other"})

    for metadata in messages:
        decision = evaluate_email_rule(
            subject=metadata.subject,
            snippet=metadata.snippet,
            body_text=metadata.body_text,
            from_header=metadata.from_header,
            internal_date=metadata.internal_date,
            timezone_name=timezone_name,
        )
        drop_reason_codes: list[str] = []

        if not decision.actionable:
            continue
        if decision.actionable:
            actionable_count += 1

        email_row = db.get(EmailMessage, metadata.message_id)
        evidence_key = {"kind": "gmail", "message_id": metadata.message_id}
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
        label_row.notes = _build_label_notes(
            decision=decision,
            drop_reason_codes=drop_reason_codes,
        )

        db.query(EmailActionItem).filter(EmailActionItem.email_id == metadata.message_id).delete(synchronize_session=False)
        if decision.actionable:
            action_items = _build_action_items_for_decision(
                decision=decision,
            )
            for item in action_items:
                db.add(
                    EmailActionItem(
                        email_id=metadata.message_id,
                        action=item.get("action"),
                        due_iso=item.get("due_iso"),
                        where_text=item.get("where_text"),
                    )
                )

        analysis_row = db.get(EmailRuleAnalysis, metadata.message_id)
        if analysis_row is None:
            analysis_row = EmailRuleAnalysis(email_id=metadata.message_id)
            db.add(analysis_row)
        analysis_row.event_flags = {key: key == decision.event_type for key in event_keys}
        snippet_text = (metadata.snippet or metadata.subject or "").strip()
        matched_rule = decision.event_type or "rule_drop"
        analysis_row.matched_snippets = (
            [{"rule": matched_rule, "snippet": snippet_text[:240]}] if snippet_text else []
        )
        analysis_row.drop_reason_codes = list(drop_reason_codes)

        route_row = db.get(EmailRoute, metadata.message_id)
        target_route = "review" if decision.actionable else "drop"
        if route_row is None:
            route_row = EmailRoute(
                email_id=metadata.message_id,
                route=target_route,
                routed_at=now,
                viewed_at=None,
                notified_at=None,
            )
            db.add(route_row)
        elif route_row.route == target_route:
            route_row.routed_at = now

    return actionable_count


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

    if route_row.route != route:
        route_row.route = route
        route_row.routed_at = now

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


def _build_label_notes(
    *,
    decision: EmailRuleDecision,
    drop_reason_codes: list[str],
) -> str:
    parts = [
        f"origin={decision.decision_origin}",
        f"score={decision.score:.2f}",
        f"confidence={decision.confidence:.2f}",
    ]
    if drop_reason_codes:
        parts.append(f"drop_reason={drop_reason_codes[0]}")
    return "; ".join(parts)


def _build_action_items_for_decision(
    *,
    decision: EmailRuleDecision,
) -> list[dict[str, str | None]]:
    return [
        {
            "action": f"Review {decision.event_type or 'timeline'} update",
            "due_iso": decision.due_at.isoformat() if decision.due_at is not None else None,
            "where_text": decision.raw_extract.get("location_text"),
        }
    ]
