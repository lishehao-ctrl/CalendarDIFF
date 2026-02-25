#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.logging import sanitize_log_message
from app.db.models import EmailActionItem, EmailMessage, EmailRoute, EmailRuleAnalysis, EmailRuleLabel, User
from app.db.session import get_session_factory
from tools.labeling.label_emails_async import read_mbox_input_emails
from tools.labeling.route_labeled import derive_primary_route
from tools.labeling.rules_extract import analyze_email_rules


@dataclass(frozen=True)
class ImportEmailRecord:
    email_id: str
    from_addr: str | None
    subject: str | None
    date_rfc822: str | None
    body_text: str
    label_payload: dict[str, Any]
    analysis: Any
    route: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import deterministic rules labels into email review DB tables.")
    parser.add_argument("--input-mbox", default=None, help="Path to source mbox input.")
    parser.add_argument("--emails-jsonl", default=None, help="Path to source emails JSONL.")
    parser.add_argument("--pred-jsonl", default=None, help="Path to rules_labeled JSONL (required with --emails-jsonl).")
    parser.add_argument("--user-id", type=int, default=1, help="Target user id (default: 1).")
    parser.add_argument("--review-threshold", type=float, default=0.75, help="Review threshold passed to route classifier.")
    parser.add_argument("--limit", type=int, default=None, help="Max rows to import.")
    parser.add_argument("--timezone", default="America/Los_Angeles", help="Timezone for deterministic rule analysis.")
    parser.add_argument("--dry-run", action="store_true", help="Compute and print stats without DB writes.")
    return parser.parse_args()


def _coerce_text(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if value is None:
        return None
    return str(value).strip() or None


def _coerce_label_row(payload: dict[str, Any], *, email_id: str) -> dict[str, Any]:
    label = _coerce_text(payload.get("label")) or "DROP"
    if label not in {"KEEP", "DROP"}:
        label = "DROP"

    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    reasons = payload.get("reasons") if isinstance(payload.get("reasons"), list) else []
    course_hints = payload.get("course_hints") if isinstance(payload.get("course_hints"), list) else []
    event_type = _coerce_text(payload.get("event_type"))
    action_items = payload.get("action_items") if isinstance(payload.get("action_items"), list) else []
    raw_extract = payload.get("raw_extract") if isinstance(payload.get("raw_extract"), dict) else {}

    normalized_items = []
    for row in action_items:
        if not isinstance(row, dict):
            continue
        normalized_items.append(
            {
                "action": _coerce_text(row.get("action")),
                "due_iso": _coerce_text(row.get("due_iso")),
                "where": _coerce_text(row.get("where")),
            }
        )

    return {
        "email_id": email_id,
        "label": label,
        "confidence": confidence,
        "reasons": [str(item).strip() for item in reasons if isinstance(item, str) and item.strip()][:3],
        "course_hints": [str(item).strip() for item in course_hints if isinstance(item, str) and item.strip()],
        "event_type": event_type if label == "KEEP" else None,
        "action_items": normalized_items,
        "raw_extract": {
            "deadline_text": _coerce_text(raw_extract.get("deadline_text")),
            "time_text": _coerce_text(raw_extract.get("time_text")),
            "location_text": _coerce_text(raw_extract.get("location_text")),
        },
        "notes": _coerce_text(payload.get("notes")),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                continue
            rows.append(payload)
    return rows


def _build_records_from_mbox(
    *,
    input_mbox: Path,
    timezone_name: str,
    review_threshold: float,
    limit: int | None,
) -> tuple[list[ImportEmailRecord], list[str]]:
    timezone_obj = ZoneInfo(timezone_name)
    parsed_rows, parse_errors = read_mbox_input_emails(input_mbox, skip_ids=set())
    errors = [sanitize_log_message(str(item.get("message_sanitized") or "mbox parse error")) for item in parse_errors]

    out: list[ImportEmailRecord] = []
    for parsed in parsed_rows:
        analysis = analyze_email_rules(
            subject=parsed.subject or "",
            body_text=parsed.body_text or "",
            date_hint=parsed.date,
            timezone=timezone_obj,
        )
        label_payload = {
            "email_id": parsed.email_id,
            "label": analysis.label,
            "confidence": analysis.confidence,
            "reasons": analysis.reasons,
            "course_hints": analysis.course_hints,
            "event_type": analysis.event_type if analysis.label == "KEEP" else None,
            "action_items": analysis.action_items,
            "raw_extract": analysis.raw_extract,
            "notes": None,
        }
        route = derive_primary_route(label_payload, review_threshold=review_threshold)
        out.append(
            ImportEmailRecord(
                email_id=parsed.email_id,
                from_addr=_coerce_text(parsed.from_field),
                subject=_coerce_text(parsed.subject),
                date_rfc822=_coerce_text(parsed.date),
                body_text=parsed.body_text,
                label_payload=label_payload,
                analysis=analysis,
                route=route,
            )
        )
        if limit is not None and len(out) >= limit:
            break
    return out, errors


def _build_records_from_jsonl_pred(
    *,
    emails_jsonl: Path,
    pred_jsonl: Path,
    timezone_name: str,
    review_threshold: float,
    limit: int | None,
) -> tuple[list[ImportEmailRecord], list[str]]:
    timezone_obj = ZoneInfo(timezone_name)
    email_rows = _read_jsonl(emails_jsonl)
    pred_rows = _read_jsonl(pred_jsonl)

    context_by_id: dict[str, dict[str, Any]] = {}
    for row in email_rows:
        email_id = _coerce_text(row.get("email_id"))
        if email_id is None:
            continue
        context_by_id[email_id] = row

    out: list[ImportEmailRecord] = []
    errors: list[str] = []
    for pred in pred_rows:
        email_id = _coerce_text(pred.get("email_id"))
        if email_id is None:
            continue
        context = context_by_id.get(email_id)
        if context is None:
            errors.append(sanitize_log_message(f"missing email context for email_id={email_id}"))
            continue
        subject = _coerce_text(context.get("subject")) or ""
        body_text = _coerce_text(context.get("body_text")) or ""
        if not body_text:
            errors.append(sanitize_log_message(f"missing body_text for email_id={email_id}"))
            continue

        analysis = analyze_email_rules(
            subject=subject,
            body_text=body_text,
            date_hint=_coerce_text(context.get("date")),
            timezone=timezone_obj,
        )
        label_payload = _coerce_label_row(pred, email_id=email_id)
        route = derive_primary_route(label_payload, review_threshold=review_threshold)
        out.append(
            ImportEmailRecord(
                email_id=email_id,
                from_addr=_coerce_text(context.get("from")),
                subject=_coerce_text(context.get("subject")),
                date_rfc822=_coerce_text(context.get("date")),
                body_text=body_text,
                label_payload=label_payload,
                analysis=analysis,
                route=route,
            )
        )
        if limit is not None and len(out) >= limit:
            break
    return out, errors


def _matched_snippets_for_storage(value: Any) -> list[dict[str, str]]:
    if isinstance(value, dict):
        rows = []
        for key, snippet in value.items():
            if isinstance(key, str) and isinstance(snippet, str) and snippet.strip():
                rows.append({"rule": key, "snippet": snippet.strip()[:240]})
        return rows
    return []


def _ensure_user_exists(db_session, *, user_id: int) -> None:
    row = db_session.get(User, user_id)
    if row is None:
        raise RuntimeError(f"user_id={user_id} does not exist")


def run_import(
    *,
    input_mbox: Path | None,
    emails_jsonl: Path | None,
    pred_jsonl: Path | None,
    user_id: int,
    review_threshold: float,
    timezone_name: str,
    limit: int | None,
    dry_run: bool,
) -> dict[str, Any]:
    if (input_mbox is None) == (emails_jsonl is None):
        raise RuntimeError("Provide exactly one mode: --input-mbox OR --emails-jsonl/--pred-jsonl.")
    if emails_jsonl is not None and pred_jsonl is None:
        raise RuntimeError("--pred-jsonl is required when --emails-jsonl is provided.")
    if pred_jsonl is not None and emails_jsonl is None:
        raise RuntimeError("--emails-jsonl is required when --pred-jsonl is provided.")
    if review_threshold < 0.0 or review_threshold > 1.0:
        raise RuntimeError("--review-threshold must be in [0, 1]")
    if limit is not None and limit <= 0:
        raise RuntimeError("--limit must be > 0")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Invalid timezone: {timezone_name}") from exc

    if input_mbox is not None:
        if not input_mbox.is_file():
            raise RuntimeError(f"Input mbox not found: {input_mbox}")
        records, ingest_errors = _build_records_from_mbox(
            input_mbox=input_mbox,
            timezone_name=timezone_name,
            review_threshold=review_threshold,
            limit=limit,
        )
        mode = "mbox"
    else:
        assert emails_jsonl is not None and pred_jsonl is not None
        if not emails_jsonl.is_file():
            raise RuntimeError(f"emails JSONL not found: {emails_jsonl}")
        if not pred_jsonl.is_file():
            raise RuntimeError(f"pred JSONL not found: {pred_jsonl}")
        records, ingest_errors = _build_records_from_jsonl_pred(
            emails_jsonl=emails_jsonl,
            pred_jsonl=pred_jsonl,
            timezone_name=timezone_name,
            review_threshold=review_threshold,
            limit=limit,
        )
        mode = "jsonl+pred"

    session_factory = get_session_factory()
    db_session = session_factory()
    stats = {
        "mode": mode,
        "dry_run": dry_run,
        "processed": 0,
        "inserted": 0,
        "updated": 0,
        "errors": len(ingest_errors),
        "route_counts": {"drop": 0, "archive": 0, "notify": 0, "review": 0},
        "ingest_errors": ingest_errors[:20],
    }
    try:
        _ensure_user_exists(db_session, user_id=user_id)
        now = datetime.now(timezone.utc)

        for record in records:
            stats["processed"] += 1
            if record.route in stats["route_counts"]:
                stats["route_counts"][record.route] += 1
            if dry_run:
                continue

            message_row = db_session.get(EmailMessage, record.email_id)
            if message_row is None:
                message_row = EmailMessage(
                    email_id=record.email_id,
                    user_id=user_id,
                    from_addr=record.from_addr,
                    subject=record.subject,
                    date_rfc822=record.date_rfc822,
                    received_at=now,
                    evidence_key=None,
                )
                db_session.add(message_row)
                stats["inserted"] += 1
            else:
                message_row.user_id = user_id
                message_row.from_addr = record.from_addr
                message_row.subject = record.subject
                message_row.date_rfc822 = record.date_rfc822
                stats["updated"] += 1

            label_payload = record.label_payload
            label_row = db_session.get(EmailRuleLabel, record.email_id)
            if label_row is None:
                label_row = EmailRuleLabel(email_id=record.email_id)
                db_session.add(label_row)
            label_row.label = str(label_payload.get("label") or "DROP")
            label_row.confidence = float(label_payload.get("confidence") or 0.0)
            label_row.reasons = label_payload.get("reasons") if isinstance(label_payload.get("reasons"), list) else []
            label_row.course_hints = (
                label_payload.get("course_hints") if isinstance(label_payload.get("course_hints"), list) else []
            )
            label_row.event_type = _coerce_text(label_payload.get("event_type"))
            label_row.raw_extract = label_payload.get("raw_extract") if isinstance(label_payload.get("raw_extract"), dict) else {}
            label_row.notes = _coerce_text(label_payload.get("notes"))

            db_session.query(EmailActionItem).filter(EmailActionItem.email_id == record.email_id).delete(synchronize_session=False)
            for item in label_payload.get("action_items", []):
                if not isinstance(item, dict):
                    continue
                db_session.add(
                    EmailActionItem(
                        email_id=record.email_id,
                        action=_coerce_text(item.get("action")),
                        due_iso=_coerce_text(item.get("due_iso")),
                        where_text=_coerce_text(item.get("where")),
                    )
                )

            analysis_row = db_session.get(EmailRuleAnalysis, record.email_id)
            if analysis_row is None:
                analysis_row = EmailRuleAnalysis(email_id=record.email_id)
                db_session.add(analysis_row)
            analysis_row.event_flags = record.analysis.event_flags if isinstance(record.analysis.event_flags, dict) else {}
            analysis_row.matched_snippets = _matched_snippets_for_storage(record.analysis.matched_snippets)
            analysis_row.drop_reason_codes = (
                list(record.analysis.drop_reason_codes) if isinstance(record.analysis.drop_reason_codes, list) else []
            )

            route_row = db_session.get(EmailRoute, record.email_id)
            if route_row is None:
                route_row = EmailRoute(
                    email_id=record.email_id,
                    route=record.route,
                    routed_at=now,
                    viewed_at=None,
                    notified_at=None,
                )
                db_session.add(route_row)
            elif route_row.route != record.route:
                route_row.route = record.route
                route_row.routed_at = now

        if dry_run:
            db_session.rollback()
        else:
            db_session.commit()
    finally:
        db_session.close()

    return stats


def main() -> int:
    try:
        args = parse_args()
        stats = run_import(
            input_mbox=Path(args.input_mbox) if args.input_mbox else None,
            emails_jsonl=Path(args.emails_jsonl) if args.emails_jsonl else None,
            pred_jsonl=Path(args.pred_jsonl) if args.pred_jsonl else None,
            user_id=int(args.user_id),
            review_threshold=float(args.review_threshold),
            timezone_name=str(args.timezone),
            limit=int(args.limit) if args.limit is not None else None,
            dry_run=bool(args.dry_run),
        )
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": sanitize_log_message(str(exc))}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
