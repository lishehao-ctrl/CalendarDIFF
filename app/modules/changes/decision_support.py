from __future__ import annotations

from datetime import date, time

from app.db.models.review import Change, ChangeIntakePhase, ChangeType
from app.modules.common.structured_copy import render_structured_text


def build_change_decision_support(
    *,
    change: Change,
    primary_source: dict | None,
    change_summary: dict | None,
    language_code: str | None = None,
) -> dict:
    before_payload = change.before_semantic_json if isinstance(change.before_semantic_json, dict) else None
    after_payload = change.after_semantic_json if isinstance(change.after_semantic_json, dict) else None
    source_label = str((primary_source or {}).get("provider") or (primary_source or {}).get("source_kind") or "source").strip()
    source_label = "Gmail" if source_label == "gmail" else "Canvas ICS" if source_label == "calendar" or source_label == "ics" else source_label.title()

    if change.change_type == ChangeType.REMOVED:
        why_now_code = "changes.removed.why_now"
        suggested_action_reason_code = "changes.removed.suggested_action_reason"
        risk_summary_code = "changes.removed.risk_summary"
        key_fact_items = _key_fact_items(
            payload=before_payload,
            source_label=source_label,
            extra=_time_change_fact_item(change_summary=change_summary),
        )
        return {
            "why_now": render_structured_text(
                code=why_now_code,
                language_code=language_code,
                params={"source_label": source_label},
                fallback=f"The latest {source_label} observation no longer supports this live item.",
            ),
            "why_now_code": why_now_code,
            "suggested_action": "review_carefully",
            "suggested_action_reason": render_structured_text(
                code=suggested_action_reason_code,
                language_code=language_code,
                fallback="Removing a live item changes canonical state and should be confirmed carefully.",
            ),
            "suggested_action_reason_code": suggested_action_reason_code,
            "risk_level": "high",
            "risk_summary": render_structured_text(
                code=risk_summary_code,
                language_code=language_code,
                fallback="Approving will remove the current live deadline from the workspace.",
            ),
            "risk_summary_code": risk_summary_code,
            "key_facts": _render_key_facts(key_fact_items, language_code=language_code),
            "key_fact_items": key_fact_items,
            "outcome_preview": _render_outcome_preview(
                language_code=language_code,
                codes={
                    "approve": "changes.removed.outcome.approve",
                    "reject": "changes.removed.outcome.reject",
                    "edit": "changes.removed.outcome.edit",
                },
                fallbacks={
                    "approve": "Remove the live item from the workspace.",
                    "reject": "Keep the current live item unchanged.",
                    "edit": "Adjust the canonical item before deciding whether to remove it.",
                },
            ),
            "outcome_preview_codes": {
                "approve": "changes.removed.outcome.approve",
                "reject": "changes.removed.outcome.reject",
                "edit": "changes.removed.outcome.edit",
            },
        }

    if change.change_type == ChangeType.DUE_CHANGED:
        before_time = _summary_value_time(change_summary, side="old")
        after_time = _summary_value_time(change_summary, side="new")
        suggested_action = "approve" if before_time and after_time else "edit"
        suggested_action_reason_code = (
            "changes.due_changed.suggested_action_reason.approve"
            if suggested_action == "approve"
            else "changes.due_changed.suggested_action_reason.edit"
        )
        suggested_reason = (
            "The item identity looks stable and the proposal mainly changes the effective due time."
            if suggested_action == "approve"
            else "The item probably needs an update, but the proposed time should be corrected before approval."
        )
        key_fact_items = _key_fact_items(
            payload=after_payload or before_payload,
            source_label=source_label,
            extra=_time_change_fact_item(change_summary=change_summary),
        )
        return {
            "why_now": render_structured_text(
                code="changes.due_changed.why_now",
                language_code=language_code,
                params={"source_label": source_label},
                fallback=f"A new {source_label} signal changed the effective time for an existing item.",
            ),
            "why_now_code": "changes.due_changed.why_now",
            "suggested_action": suggested_action,
            "suggested_action_reason": render_structured_text(
                code=suggested_action_reason_code,
                language_code=language_code,
                fallback=suggested_reason,
            ),
            "suggested_action_reason_code": suggested_action_reason_code,
            "risk_level": "medium",
            "risk_summary": render_structured_text(
                code="changes.due_changed.risk_summary",
                language_code=language_code,
                fallback="Approving will update the live deadline shown in the workspace.",
            ),
            "risk_summary_code": "changes.due_changed.risk_summary",
            "key_facts": _render_key_facts(key_fact_items, language_code=language_code),
            "key_fact_items": key_fact_items,
            "outcome_preview": _render_outcome_preview(
                language_code=language_code,
                codes={
                    "approve": "changes.due_changed.outcome.approve",
                    "reject": "changes.due_changed.outcome.reject",
                    "edit": "changes.due_changed.outcome.edit",
                },
                fallbacks={
                    "approve": "Update the live deadline to the proposed time.",
                    "reject": "Keep the current live deadline unchanged.",
                    "edit": "Correct the proposed time before updating the live deadline.",
                },
            ),
            "outcome_preview_codes": {
                "approve": "changes.due_changed.outcome.approve",
                "reject": "changes.due_changed.outcome.reject",
                "edit": "changes.due_changed.outcome.edit",
            },
        }

    if change.intake_phase == ChangeIntakePhase.BASELINE:
        key_fact_items = _key_fact_items(
            payload=after_payload,
            source_label=source_label,
            extra=_time_change_fact_item(change_summary=change_summary),
        )
        return {
            "why_now": render_structured_text(
                code="changes.baseline_created.why_now",
                language_code=language_code,
                params={"source_label": source_label},
                fallback=f"This baseline item was imported from {source_label} and still needs confirmation before monitoring is fully live.",
            ),
            "why_now_code": "changes.baseline_created.why_now",
            "suggested_action": "approve",
            "suggested_action_reason": render_structured_text(
                code="changes.baseline_created.suggested_action_reason",
                language_code=language_code,
                fallback="If the item identity and time look right, approving it helps finish Initial Review faster.",
            ),
            "suggested_action_reason_code": "changes.baseline_created.suggested_action_reason",
            "risk_level": "low",
            "risk_summary": render_structured_text(
                code="changes.baseline_created.risk_summary",
                language_code=language_code,
                fallback="Approving adds this item into the live baseline used for future replay detection.",
            ),
            "risk_summary_code": "changes.baseline_created.risk_summary",
            "key_facts": _render_key_facts(key_fact_items, language_code=language_code),
            "key_fact_items": key_fact_items,
            "outcome_preview": _render_outcome_preview(
                language_code=language_code,
                codes={
                    "approve": "changes.baseline_created.outcome.approve",
                    "reject": "changes.baseline_created.outcome.reject",
                    "edit": "changes.baseline_created.outcome.edit",
                },
                fallbacks={
                    "approve": "Add this item into the live baseline.",
                    "reject": "Leave this item out of the live baseline.",
                    "edit": "Correct the imported details before adding the item into the live baseline.",
                },
            ),
            "outcome_preview_codes": {
                "approve": "changes.baseline_created.outcome.approve",
                "reject": "changes.baseline_created.outcome.reject",
                "edit": "changes.baseline_created.outcome.edit",
            },
        }

    key_fact_items = _key_fact_items(
        payload=after_payload,
        source_label=source_label,
        extra=_time_change_fact_item(change_summary=change_summary),
    )
    return {
        "why_now": render_structured_text(
            code="changes.created.why_now",
            language_code=language_code,
            params={"source_label": source_label},
            fallback=f"A new {source_label} signal looks like a newly announced grade-relevant item.",
        ),
        "why_now_code": "changes.created.why_now",
        "suggested_action": "approve",
        "suggested_action_reason": render_structured_text(
            code="changes.created.suggested_action_reason",
            language_code=language_code,
            fallback="If the item and time look correct, approving it makes the new item live immediately.",
        ),
        "suggested_action_reason_code": "changes.created.suggested_action_reason",
        "risk_level": "medium",
        "risk_summary": render_structured_text(
            code="changes.created.risk_summary",
            language_code=language_code,
            fallback="Approving will add a new live item to the workspace.",
        ),
        "risk_summary_code": "changes.created.risk_summary",
        "key_facts": _render_key_facts(key_fact_items, language_code=language_code),
        "key_fact_items": key_fact_items,
        "outcome_preview": _render_outcome_preview(
            language_code=language_code,
            codes={
                "approve": "changes.created.outcome.approve",
                "reject": "changes.created.outcome.reject",
                "edit": "changes.created.outcome.edit",
            },
            fallbacks={
                "approve": "Create a new live item in the workspace.",
                "reject": "Ignore this proposed new item.",
                "edit": "Correct the item details before creating the live item.",
            },
        ),
        "outcome_preview_codes": {
            "approve": "changes.created.outcome.approve",
            "reject": "changes.created.outcome.reject",
            "edit": "changes.created.outcome.edit",
        },
    }


def _key_fact_items(*, payload: dict | None, source_label: str, extra: tuple[str, str] | None) -> list[dict]:
    facts: list[dict] = []
    if payload is not None:
        course = _course_label(payload)
        if course:
            facts.append({"code": "course", "value": course})
        item = _item_label(payload)
        if item:
            facts.append({"code": "item", "value": item})
        due = _due_label(payload)
        if due:
            facts.append({"code": "proposed_time", "value": due})
    facts.append({"code": "primary_source", "value": source_label})
    if extra:
        extra_code, extra_value = extra
        facts.append({"code": extra_code, "value": extra_value})
    return facts[:4]


def _render_key_facts(items: list[dict], *, language_code: str | None) -> list[str]:
    rendered: list[str] = []
    for item in items:
        code = str(item.get("code") or "")
        value = str(item.get("value") or "")
        if not value:
            continue
        rendered.append(
            render_structured_text(
                code=f"changes.key_fact.{code}",
                language_code=language_code,
                params={"value": value},
                fallback=value,
            )
        )
    return rendered[:4]


def _render_outcome_preview(
    *,
    language_code: str | None,
    codes: dict[str, str],
    fallbacks: dict[str, str],
) -> dict[str, str]:
    return {
        key: render_structured_text(
            code=codes[key],
            language_code=language_code,
            fallback=fallbacks[key],
        )
        for key in ("approve", "reject", "edit")
    }


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


def _time_change_fact_item(*, change_summary: dict | None) -> tuple[str, str] | None:
    if not isinstance(change_summary, dict):
        return None
    old_value = _summary_value_time(change_summary, side="old")
    new_value = _summary_value_time(change_summary, side="new")
    if old_value and new_value and old_value != new_value:
        return ("time_change", f"{old_value} -> {new_value}")
    if new_value:
        return ("effective_time", new_value)
    if old_value:
        return ("current_time", old_value)
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
