from __future__ import annotations

from datetime import date, time

from app.db.models.review import Change, ChangeIntakePhase, ChangeType


def build_change_decision_support(
    *,
    change: Change,
    primary_source: dict | None,
    change_summary: dict | None,
) -> dict:
    before_payload = change.before_semantic_json if isinstance(change.before_semantic_json, dict) else None
    after_payload = change.after_semantic_json if isinstance(change.after_semantic_json, dict) else None
    source_label = str((primary_source or {}).get("provider") or (primary_source or {}).get("source_kind") or "source").strip()
    source_label = "Gmail" if source_label == "gmail" else "Canvas ICS" if source_label == "calendar" or source_label == "ics" else source_label.title()

    if change.change_type == ChangeType.REMOVED:
        return {
            "why_now": f"The latest {source_label} observation no longer supports this live item.",
            "suggested_action": "review_carefully",
            "suggested_action_reason": "Removing a live item changes canonical state and should be confirmed carefully.",
            "risk_level": "high",
            "risk_summary": "Approving will remove the current live deadline from the workspace.",
            "key_facts": _key_facts(
                payload=before_payload,
                source_label=source_label,
                extra=_time_change_fact(change_summary=change_summary),
            ),
            "outcome_preview": {
                "approve": "Remove the live item from the workspace.",
                "reject": "Keep the current live item unchanged.",
                "edit": "Adjust the canonical item before deciding whether to remove it.",
            },
        }

    if change.change_type == ChangeType.DUE_CHANGED:
        before_time = _summary_value_time(change_summary, side="old")
        after_time = _summary_value_time(change_summary, side="new")
        suggested_action = "approve" if before_time and after_time else "edit"
        suggested_reason = (
            "The item identity looks stable and the proposal mainly changes the effective due time."
            if suggested_action == "approve"
            else "The item probably needs an update, but the proposed time should be corrected before approval."
        )
        return {
            "why_now": f"A new {source_label} signal changed the effective time for an existing item.",
            "suggested_action": suggested_action,
            "suggested_action_reason": suggested_reason,
            "risk_level": "medium",
            "risk_summary": "Approving will update the live deadline shown in the workspace.",
            "key_facts": _key_facts(
                payload=after_payload or before_payload,
                source_label=source_label,
                extra=_time_change_fact(change_summary=change_summary),
            ),
            "outcome_preview": {
                "approve": "Update the live deadline to the proposed time.",
                "reject": "Keep the current live deadline unchanged.",
                "edit": "Correct the proposed time before updating the live deadline.",
            },
        }

    if change.intake_phase == ChangeIntakePhase.BASELINE:
        return {
            "why_now": f"This baseline item was imported from {source_label} and still needs confirmation before monitoring is fully live.",
            "suggested_action": "approve",
            "suggested_action_reason": "If the item identity and time look right, approving it helps finish Initial Review faster.",
            "risk_level": "low",
            "risk_summary": "Approving adds this item into the live baseline used for future replay detection.",
            "key_facts": _key_facts(
                payload=after_payload,
                source_label=source_label,
                extra=_time_change_fact(change_summary=change_summary),
            ),
            "outcome_preview": {
                "approve": "Add this item into the live baseline.",
                "reject": "Leave this item out of the live baseline.",
                "edit": "Correct the imported details before adding the item into the live baseline.",
            },
        }

    return {
        "why_now": f"A new {source_label} signal looks like a newly announced grade-relevant item.",
        "suggested_action": "approve",
        "suggested_action_reason": "If the item and time look correct, approving it makes the new item live immediately.",
        "risk_level": "medium",
        "risk_summary": "Approving will add a new live item to the workspace.",
        "key_facts": _key_facts(
            payload=after_payload,
            source_label=source_label,
            extra=_time_change_fact(change_summary=change_summary),
        ),
        "outcome_preview": {
            "approve": "Create a new live item in the workspace.",
            "reject": "Ignore this proposed new item.",
            "edit": "Correct the item details before creating the live item.",
        },
    }


def _key_facts(*, payload: dict | None, source_label: str, extra: str | None) -> list[str]:
    facts: list[str] = []
    if payload is not None:
        course = _course_label(payload)
        if course:
            facts.append(f"Course: {course}")
        item = _item_label(payload)
        if item:
            facts.append(f"Item: {item}")
        due = _due_label(payload)
        if due:
            facts.append(f"Proposed time: {due}")
    facts.append(f"Primary source: {source_label}")
    if extra:
        facts.append(extra)
    return facts[:4]


def _course_label(payload: dict) -> str | None:
    dept = payload.get("course_dept")
    number = payload.get("course_number")
    suffix = payload.get("course_suffix")
    if not isinstance(dept, str) or not dept.strip() or not isinstance(number, int):
        return None
    suffix_text = f"{suffix}" if isinstance(suffix, str) and suffix.strip() else ""
    return f"{dept.strip().upper()} {number}{suffix_text}"


def _item_label(payload: dict) -> str | None:
    family_name = payload.get("family_name")
    event_name = payload.get("event_name")
    ordinal = payload.get("ordinal")
    if isinstance(event_name, str) and event_name.strip():
        return event_name.strip()
    if isinstance(family_name, str) and family_name.strip():
        if isinstance(ordinal, int) and ordinal > 0:
            return f"{family_name.strip()} {ordinal}"
        return family_name.strip()
    return None


def _due_label(payload: dict) -> str | None:
    due_date = _coerce_date(payload.get("due_date"))
    due_time = _coerce_time(payload.get("due_time"))
    time_precision = str(payload.get("time_precision") or "")
    if due_date is None:
        return None
    if time_precision == "date_only" or due_time is None:
        return due_date.isoformat()
    return f"{due_date.isoformat()} {due_time.strftime('%H:%M')}"


def _time_change_fact(*, change_summary: dict | None) -> str | None:
    if not isinstance(change_summary, dict):
        return None
    old_value = _summary_value_time(change_summary, side="old")
    new_value = _summary_value_time(change_summary, side="new")
    if old_value and new_value and old_value != new_value:
        return f"Time change: {old_value} -> {new_value}"
    if new_value:
        return f"Effective time: {new_value}"
    if old_value:
        return f"Current time: {old_value}"
    return None


def _summary_value_time(change_summary: dict | None, *, side: str) -> str | None:
    if not isinstance(change_summary, dict):
        return None
    side_payload = change_summary.get(side)
    if not isinstance(side_payload, dict):
        return None
    value = side_payload.get("value_time")
    if isinstance(value, str) and value.strip():
        return value.strip().replace("T", " ").replace("Z", " UTC")
    return None


def _coerce_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except Exception:
            return None
    return None


def _coerce_time(value: object) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = time.fromisoformat(value)
        except Exception:
            return None
        return parsed.replace(tzinfo=None)
    return None


__all__ = ["build_change_decision_support"]
