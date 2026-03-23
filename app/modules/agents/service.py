from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.modules.changes.change_listing_service import get_change, list_changes
from app.modules.common.api_errors import api_error_detail
from app.modules.sources.read_service import build_source_read_payload
from app.modules.sources.sources_service import get_input_source
from app.modules.sources.status_projection import build_source_observability_payload, build_sync_request_status_payload, get_display_sync_request_for_source
from app.modules.workbench.summary_service import get_changes_workbench_summary


class AgentContextNotFoundError(RuntimeError):
    def __init__(self, *, code: str, message: str, message_code: str) -> None:
        super().__init__(message)
        self.detail = api_error_detail(code=code, message=message, message_code=message_code)


def build_workspace_agent_context(db: Session, *, user_id: int) -> dict:
    summary = get_changes_workbench_summary(db=db, user_id=user_id)
    top_pending_changes = list_changes(
        db,
        user_id=user_id,
        review_status="pending",
        review_bucket="all",
        intake_phase="all",
        source_id=None,
        limit=5,
        offset=0,
    )
    return {
        "generated_at": datetime.now(timezone.utc),
        "summary": summary,
        "top_pending_changes": top_pending_changes,
        "recommended_next_action": _workspace_recommended_next_action(summary=summary),
        "blocking_conditions": _workspace_blocking_conditions(summary=summary),
        "available_next_tools": _workspace_available_next_tools(summary=summary),
    }


def build_change_agent_context(db: Session, *, user_id: int, change_id: int) -> dict:
    change = get_change(db, user_id=user_id, change_id=change_id)
    if change is None:
        raise AgentContextNotFoundError(
            code="agents.context.change_not_found",
            message="Change not found",
            message_code="agents.context.change_not_found",
        )
    return {
        "generated_at": datetime.now(timezone.utc),
        "change": change,
        "recommended_next_action": _change_recommended_next_action(change=change),
        "blocking_conditions": _change_blocking_conditions(change=change),
        "available_next_tools": _change_available_next_tools(change=change),
    }


def build_source_agent_context(db: Session, *, user_id: int, source_id: int) -> dict:
    source = get_input_source(db, user_id=user_id, source_id=source_id)
    if source is None:
        raise AgentContextNotFoundError(
            code="agents.context.source_not_found",
            message="Source not found",
            message_code="agents.context.source_not_found",
        )
    source_payload = build_source_read_payload(db, source=source)
    observability = build_source_observability_payload(db, source_id=source.id)
    active_row = get_display_sync_request_for_source(db, source_id=source.id)
    active_sync_request = build_sync_request_status_payload(db, sync_request=active_row) if active_row is not None else None
    return {
        "generated_at": datetime.now(timezone.utc),
        "source": source_payload,
        "observability": observability,
        "active_sync_request": active_sync_request,
        "recommended_next_action": _source_recommended_next_action(source=source_payload, observability=observability),
        "blocking_conditions": _source_blocking_conditions(source=source_payload, observability=observability),
        "available_next_tools": _source_available_next_tools(source=source_payload, observability=observability),
    }


def _workspace_recommended_next_action(*, summary: dict) -> dict:
    posture = summary.get("workspace_posture") or {}
    next_action = posture.get("next_action") or {}
    lane = str(next_action.get("lane") or "changes")
    return {
        "lane": lane,
        "label": str(next_action.get("label") or "Open Changes"),
        "reason": str(next_action.get("reason") or ""),
        "reason_code": str(next_action.get("reason_code") or "agents.context.workspace.next_action"),
        "reason_params": next_action.get("reason_params") or {},
        "risk_level": _workspace_risk_level(summary=summary),
        "recommended_tool": _lane_to_tool(lane),
    }


def _workspace_risk_level(*, summary: dict) -> str:
    posture = summary.get("workspace_posture") or {}
    phase = str(posture.get("phase") or "")
    if phase == "attention_required":
        return "high"
    if phase in {"baseline_import", "initial_review"}:
        return "medium"
    if int(summary.get("changes_pending") or 0) > 0:
        return "medium"
    return "low"


def _workspace_blocking_conditions(*, summary: dict) -> list[dict]:
    items: list[dict] = []
    sources = summary.get("sources") or {}
    if int(sources.get("blocking_count") or 0) > 0:
        items.append(
            {
                "code": str(sources.get("reason_code") or "sources_attention_required"),
                "message": str(sources.get("message") or "Source attention is required before relying on live monitoring."),
                "severity": "blocking",
            }
        )
    if int(summary.get("baseline_review_pending") or 0) > 0:
        items.append(
            {
                "code": "baseline_review_pending",
                "message": "Baseline import review is not finished yet.",
                "severity": "warning",
            }
        )
    return items


def _workspace_available_next_tools(*, summary: dict) -> list[str]:
    posture = summary.get("workspace_posture") or {}
    lane = str((posture.get("next_action") or {}).get("lane") or "changes")
    tools = [_lane_to_tool(lane), "review_change_context", "review_source_context"]
    if int(summary.get("baseline_review_pending") or 0) > 0:
        tools.append("review_initial_review_changes")
    if int(summary.get("changes_pending") or 0) > 0:
        tools.append("review_replay_changes")
    if int((summary.get("families") or {}).get("attention_count") or 0) > 0:
        tools.append("review_families")
    return _dedupe_strings(tools)


def _change_recommended_next_action(*, change: dict) -> dict:
    support = change.get("decision_support") or {}
    review_bucket = str(change.get("review_bucket") or "changes")
    suggested_action = str(support.get("suggested_action") or "review_carefully")
    return {
        "lane": review_bucket,
        "label": _change_action_label(suggested_action),
        "reason": str(support.get("suggested_action_reason") or ""),
        "reason_code": str(support.get("suggested_action_reason_code") or "agents.context.change.suggested_action"),
        "reason_params": {},
        "risk_level": str(support.get("risk_level") or "medium"),
        "recommended_tool": _change_action_tool(suggested_action),
    }


def _change_blocking_conditions(*, change: dict) -> list[dict]:
    conditions: list[dict] = []
    if str(change.get("review_status") or "") != "pending":
        conditions.append(
            {
                "code": "change_already_reviewed",
                "message": "This change has already been reviewed.",
                "severity": "blocking",
            }
        )
    support = change.get("decision_support") or {}
    if str(support.get("risk_level") or "") == "high":
        conditions.append(
            {
                "code": "high_risk_change",
                "message": str(support.get("risk_summary") or "This change should be reviewed carefully before confirmation."),
                "severity": "warning",
            }
        )
    return conditions


def _change_available_next_tools(*, change: dict) -> list[str]:
    tools = ["view_change"]
    evidence = change.get("evidence_availability") or {}
    if bool(evidence.get("before")):
        tools.append("view_before_evidence")
    if bool(evidence.get("after")):
        tools.append("view_after_evidence")
    if str(change.get("review_status") or "") == "pending":
        tools.extend(
            [
                "submit_change_decision",
                "preview_change_edit",
                "preview_label_learning",
                "review_families",
            ]
        )
    return _dedupe_strings(tools)


def _source_recommended_next_action(*, source: dict, observability: dict) -> dict:
    guidance = observability.get("operator_guidance") or {}
    recovery = observability.get("source_recovery") or {}
    lane = "sources"
    recommended_action = str(guidance.get("recommended_action") or "continue_review")
    return {
        "lane": lane,
        "label": _source_action_label(recommended_action),
        "reason": str(guidance.get("message") or recovery.get("impact_summary") or ""),
        "reason_code": str(guidance.get("reason_code") or "agents.context.source.next_action"),
        "reason_params": guidance.get("message_params") or {},
        "risk_level": _source_risk_level(observability=observability),
        "recommended_tool": _source_recommended_tool(source=source, observability=observability),
    }


def _source_risk_level(*, observability: dict) -> str:
    recovery = observability.get("source_recovery") or {}
    trust_state = str(recovery.get("trust_state") or "")
    if trust_state == "blocked":
        return "high"
    if trust_state in {"partial", "stale"}:
        return "medium"
    return "low"


def _source_blocking_conditions(*, source: dict, observability: dict) -> list[dict]:
    conditions: list[dict] = []
    guidance = observability.get("operator_guidance") or {}
    recovery = observability.get("source_recovery") or {}
    if str(guidance.get("severity") or "") == "blocking":
        conditions.append(
            {
                "code": str(guidance.get("reason_code") or "source_runtime_blocking"),
                "message": str(guidance.get("message") or "Runtime attention is required."),
                "severity": "blocking",
            }
        )
    if str(recovery.get("trust_state") or "") in {"blocked", "partial", "stale"}:
        severity = "blocking" if str(recovery.get("trust_state") or "") == "blocked" else "warning"
        conditions.append(
            {
                "code": str(recovery.get("impact_code") or "source_recovery_attention"),
                "message": str(recovery.get("impact_summary") or "Source trust is degraded."),
                "severity": severity,
            }
        )
    if source.get("provider") == "gmail" and str(source.get("oauth_connection_status") or "") == "not_connected":
        conditions.append(
            {
                "code": "gmail_oauth_not_connected",
                "message": "Gmail is not currently connected.",
                "severity": "blocking",
            }
        )
    return _dedupe_conditions(conditions)


def _source_available_next_tools(*, source: dict, observability: dict) -> list[str]:
    tools = ["review_source_observability", "view_sync_history", "review_change_context"]
    if bool(source.get("is_active")):
        tools.append("run_source_sync")
    if source.get("provider") == "gmail":
        tools.append("start_oauth_session")
    if str((observability.get("source_recovery") or {}).get("next_action") or "") == "reconnect_gmail":
        tools.append("reconnect_source")
    return _dedupe_strings(tools)


def _lane_to_tool(lane: str) -> str:
    return {
        "sources": "review_sources",
        "initial_review": "review_initial_review_changes",
        "changes": "review_replay_changes",
        "families": "review_families",
        "manual": "review_manual",
    }.get(lane, "review_replay_changes")


def _change_action_label(action: str) -> str:
    return {
        "approve": "Approve change",
        "reject": "Reject change",
        "edit": "Edit before approval",
        "review_carefully": "Review carefully",
    }.get(action, "Review change")


def _change_action_tool(action: str) -> str:
    return {
        "approve": "submit_change_decision",
        "reject": "submit_change_decision",
        "edit": "preview_change_edit",
        "review_carefully": "view_change",
    }.get(action, "view_change")


def _source_action_label(action: str) -> str:
    return {
        "continue_review": "Continue review",
        "continue_review_with_caution": "Continue review with caution",
        "wait_for_runtime": "Wait for runtime",
        "investigate_runtime": "Investigate runtime",
    }.get(action, "Review source")


def _source_recommended_tool(*, source: dict, observability: dict) -> str:
    recovery = observability.get("source_recovery") or {}
    next_action = str(recovery.get("next_action") or "")
    if next_action == "reconnect_gmail":
        return "reconnect_source"
    if next_action == "retry_sync":
        return "run_source_sync"
    return "review_source_observability"


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _dedupe_conditions(values: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for value in values:
        key = (str(value.get("code") or ""), str(value.get("message") or ""))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


__all__ = [
    "AgentContextNotFoundError",
    "build_change_agent_context",
    "build_source_agent_context",
    "build_workspace_agent_context",
]
