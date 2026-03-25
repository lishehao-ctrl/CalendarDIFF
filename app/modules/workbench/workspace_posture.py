from __future__ import annotations

from datetime import UTC, datetime

from app.modules.common.structured_copy import render_structured_text


def build_workspace_posture(
    *,
    baseline_review_pending: int,
    baseline_review_reviewed: int,
    baseline_review_total: int,
    baseline_review_completed_at: datetime | None,
    changes_pending: int,
    families_attention_count: int,
    manual_active_count: int,
    sources_summary: dict,
    source_product_phases: list[str],
    monitoring_live_since: datetime | None,
    replay_active: bool,
    language_code: str | None = None,
) -> dict:
    if int(sources_summary.get("blocking_count") or 0) > 0 or int(sources_summary.get("active_count") or 0) == 0:
        phase = "attention_required"
        reason_code = "workspace_posture.next_action.sources_attention_required"
        reason_params = {
            "message": str(sources_summary.get("message") or "Source attention is required before relying on live monitoring."),
        }
        next_action = {
            "lane": "sources",
            "label": render_structured_text(
                code=f"{reason_code}.label",
                language_code=language_code,
                fallback="Open Sources",
            ),
            "reason": render_structured_text(
                code=f"{reason_code}.reason",
                language_code=language_code,
                params=reason_params,
                fallback=reason_params["message"],
            ),
            "reason_code": reason_code,
            "reason_params": reason_params,
        }
    elif "importing_baseline" in source_product_phases:
        phase = "baseline_import"
        reason_code = "workspace_posture.next_action.baseline_import_running"
        next_action = {
            "lane": "sources",
            "label": render_structured_text(code=f"{reason_code}.label", language_code=language_code, fallback="Open Sources"),
            "reason": render_structured_text(
                code=f"{reason_code}.reason",
                language_code=language_code,
                fallback="At least one source is still building its baseline import.",
            ),
            "reason_code": reason_code,
            "reason_params": {},
        }
    elif baseline_review_pending > 0 or "needs_initial_review" in source_product_phases:
        phase = "initial_review"
        reason_code = "workspace_posture.next_action.initial_review_pending"
        reason_params = {"pending_count": baseline_review_pending}
        next_action = {
            "lane": "initial_review",
            "label": render_structured_text(
                code=f"{reason_code}.label",
                language_code=language_code,
                fallback="Open Baseline Review",
            ),
            "reason": render_structured_text(
                code=f"{reason_code}.reason",
                language_code=language_code,
                params=reason_params,
                fallback=f"{baseline_review_pending} baseline items still need review before monitoring is fully live.",
            ),
            "reason_code": reason_code,
            "reason_params": reason_params,
        }
    else:
        phase = "monitoring_live"
        if changes_pending > 0:
            reason_code = "workspace_posture.next_action.replay_changes_pending"
            reason_params = {"pending_count": changes_pending}
            next_action = {
                "lane": "changes",
                "label": render_structured_text(
                    code=f"{reason_code}.label",
                    language_code=language_code,
                    fallback="Open Replay Review",
                ),
                "reason": render_structured_text(
                    code=f"{reason_code}.reason",
                    language_code=language_code,
                    params=reason_params,
                    fallback=f"{changes_pending} replay changes are waiting for review decisions.",
                ),
                "reason_code": reason_code,
                "reason_params": reason_params,
            }
        elif families_attention_count > 0:
            reason_code = "workspace_posture.next_action.families_attention_required"
            reason_params = {"attention_count": families_attention_count}
            next_action = {
                "lane": "families",
                "label": render_structured_text(code=f"{reason_code}.label", language_code=language_code, fallback="Open Families"),
                "reason": render_structured_text(
                    code=f"{reason_code}.reason",
                    language_code=language_code,
                    params=reason_params,
                    fallback="Naming governance still needs attention.",
                ),
                "reason_code": reason_code,
                "reason_params": reason_params,
            }
        elif manual_active_count > 0:
            reason_code = "workspace_posture.next_action.manual_repairs_active"
            reason_params = {"active_event_count": manual_active_count}
            next_action = {
                "lane": "manual",
                "label": render_structured_text(code=f"{reason_code}.label", language_code=language_code, fallback="Open Manual"),
                "reason": render_structured_text(
                    code=f"{reason_code}.reason",
                    language_code=language_code,
                    params=reason_params,
                    fallback="Fallback manual repairs are still active.",
                ),
                "reason_code": reason_code,
                "reason_params": reason_params,
            }
        else:
            reason_code = "workspace_posture.next_action.monitoring_live_default"
            next_action = {
                "lane": "changes",
                "label": render_structured_text(code=f"{reason_code}.label", language_code=language_code, fallback="Open Replay Review"),
                "reason": render_structured_text(
                    code=f"{reason_code}.reason",
                    language_code=language_code,
                    fallback="Monitoring is live. Replay Review is the main daily workspace.",
                ),
                "reason_code": reason_code,
                "reason_params": {},
            }

    completion_percent = 100 if baseline_review_total == 0 else int(round((baseline_review_reviewed / baseline_review_total) * 100))
    return {
        "phase": phase,
        "initial_review": {
            "pending_count": baseline_review_pending,
            "reviewed_count": baseline_review_reviewed,
            "total_count": baseline_review_total,
            "completion_percent": completion_percent,
            "completed_at": baseline_review_completed_at,
        },
        "monitoring": {
            "live_since": monitoring_live_since,
            "replay_active": replay_active,
            "active_source_count": int(sources_summary.get("active_count") or 0),
        },
        "next_action": next_action,
    }


def compute_monitoring_live_since(*, source_observability_rows: list[dict]) -> datetime | None:
    candidates: list[datetime] = []
    for row in source_observability_rows:
        bootstrap = row.get("bootstrap") if isinstance(row, dict) else None
        bootstrap_summary = row.get("bootstrap_summary") if isinstance(row, dict) else None
        if not isinstance(bootstrap, dict) or not isinstance(bootstrap_summary, dict):
            continue
        if str(bootstrap_summary.get("state") or "") not in {"completed", "review_required"}:
            continue
        applied_at = _coerce_datetime(bootstrap.get("applied_at")) or _coerce_datetime(bootstrap.get("updated_at"))
        if applied_at is not None:
            candidates.append(applied_at)
    return min(candidates) if candidates else None


def _coerce_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except Exception:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


__all__ = [
    "build_workspace_posture",
    "compute_monitoring_live_since",
]
