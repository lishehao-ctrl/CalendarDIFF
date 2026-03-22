from __future__ import annotations

from datetime import UTC, datetime


def build_source_product_phase(
    *,
    bootstrap_summary: dict | None,
    source_recovery: dict | None,
) -> str:
    bootstrap_state = str((bootstrap_summary or {}).get("state") or "")
    if bootstrap_state == "running":
        return "importing_baseline"
    if bootstrap_state == "review_required":
        return "needs_initial_review"

    trust_state = str((source_recovery or {}).get("trust_state") or "")
    if trust_state in {"stale", "blocked"}:
        return "needs_attention"
    return "monitoring_live"


def build_source_recovery_payload(
    *,
    provider: str,
    oauth_connection_status: str | None,
    runtime_state: str | None,
    operator_guidance: dict | None,
    bootstrap_summary: dict | None,
    active_payload: dict | None,
    latest_replay_payload: dict | None,
    bootstrap_payload: dict | None,
) -> dict:
    bootstrap_state = str((bootstrap_summary or {}).get("state") or "")
    active_status = str((active_payload or {}).get("status") or "")
    latest_replay_status = str((latest_replay_payload or {}).get("status") or "")
    guidance_action = str((operator_guidance or {}).get("recommended_action") or "")
    guidance_severity = str((operator_guidance or {}).get("severity") or "")

    if provider == "gmail" and oauth_connection_status == "not_connected":
        return {
            "trust_state": "blocked",
            "impact_summary": "New Gmail-based changes may be missing until the mailbox is reconnected.",
            "impact_code": "sources.recovery.gmail.oauth_disconnected",
            "next_action": "reconnect_gmail",
            "next_action_label": "Reconnect Gmail",
            "last_good_sync_at": _last_good_sync_at(latest_replay_payload=latest_replay_payload, bootstrap_payload=bootstrap_payload),
            "degraded_since": _pick_degraded_since(latest_replay_payload=latest_replay_payload, active_payload=active_payload),
            "recovery_steps": [
                "Reconnect the mailbox to restore intake.",
                "Wait for the next sync to finish before trusting new email-backed changes.",
            ],
            "recovery_step_codes": [
                "sources.recovery.gmail.step.reconnect_mailbox",
                "sources.recovery.gmail.step.wait_for_sync",
            ],
        }

    if runtime_state == "rebind_pending" and provider == "ics":
        return {
            "trust_state": "blocked",
            "impact_summary": "Canvas ICS needs updated monitoring settings before new calendar updates can be trusted.",
            "impact_code": "sources.recovery.ics.rebind_pending",
            "next_action": "update_ics",
            "next_action_label": "Update Canvas ICS",
            "last_good_sync_at": _last_good_sync_at(latest_replay_payload=latest_replay_payload, bootstrap_payload=bootstrap_payload),
            "degraded_since": _pick_degraded_since(latest_replay_payload=latest_replay_payload, active_payload=active_payload),
            "recovery_steps": [
                "Open the Canvas ICS connection flow and confirm the current feed settings.",
                "Run another sync after saving the updated link.",
            ],
            "recovery_step_codes": [
                "sources.recovery.ics.step.confirm_feed_settings",
                "sources.recovery.ics.step.run_sync_after_update",
            ],
        }

    if guidance_action == "investigate_runtime" or latest_replay_status == "FAILED":
        return {
            "trust_state": "stale",
            "impact_summary": _runtime_failure_summary(provider=provider),
            "impact_code": f"sources.recovery.{provider or 'source'}.runtime_failed",
            "next_action": "retry_sync",
            "next_action_label": "Retry sync",
            "last_good_sync_at": _last_good_sync_at(latest_replay_payload=latest_replay_payload, bootstrap_payload=bootstrap_payload),
            "degraded_since": _pick_degraded_since(latest_replay_payload=latest_replay_payload, active_payload=active_payload),
            "recovery_steps": [
                "Retry the source sync.",
                "If the next sync also fails, investigate the source connection before trusting new changes.",
            ],
            "recovery_step_codes": [
                "sources.recovery.runtime_failed.step.retry_sync",
                "sources.recovery.runtime_failed.step.investigate_if_repeat",
            ],
        }

    if guidance_action == "wait_for_runtime" and guidance_severity == "blocking":
        return {
            "trust_state": "blocked",
            "impact_summary": _runtime_stalled_summary(provider=provider),
            "impact_code": f"sources.recovery.{provider or 'source'}.runtime_stalled",
            "next_action": "wait",
            "next_action_label": "Wait for runtime",
            "last_good_sync_at": _last_good_sync_at(latest_replay_payload=latest_replay_payload, bootstrap_payload=bootstrap_payload),
            "degraded_since": _pick_degraded_since(latest_replay_payload=latest_replay_payload, active_payload=active_payload),
            "recovery_steps": [
                "Let the current runtime work finish or recover.",
                "Only trust new changes after progress starts moving again or the sync completes.",
            ],
            "recovery_step_codes": [
                "sources.recovery.runtime_stalled.step.wait",
                "sources.recovery.runtime_stalled.step.resume_after_progress",
            ],
        }

    if bootstrap_state == "running":
        return {
            "trust_state": "partial",
            "impact_summary": "Baseline import is still building this source before steady-state monitoring begins.",
            "impact_code": "sources.recovery.baseline.running",
            "next_action": "wait",
            "next_action_label": "Wait for baseline import",
            "last_good_sync_at": _last_good_sync_at(latest_replay_payload=latest_replay_payload, bootstrap_payload=bootstrap_payload),
            "degraded_since": _pick_degraded_since(latest_replay_payload=latest_replay_payload, active_payload=active_payload),
            "recovery_steps": [
                "Wait for the initial import to complete.",
                "Review any baseline items before treating this source as fully live.",
            ],
            "recovery_step_codes": [
                "sources.recovery.baseline.running.step.wait",
                "sources.recovery.baseline.running.step.review_after_import",
            ],
        }

    if bootstrap_state == "review_required":
        return {
            "trust_state": "partial",
            "impact_summary": "Baseline import finished, but Initial Review still has items waiting before this source is fully trusted.",
            "impact_code": "sources.recovery.baseline.review_required",
            "next_action": "wait",
            "next_action_label": "Finish Initial Review",
            "last_good_sync_at": _last_good_sync_at(latest_replay_payload=latest_replay_payload, bootstrap_payload=bootstrap_payload),
            "degraded_since": _pick_degraded_since(latest_replay_payload=latest_replay_payload, active_payload=active_payload),
            "recovery_steps": [
                "Finish Initial Review for this source.",
                "After that, use Replay Review for day-to-day change handling.",
            ],
            "recovery_step_codes": [
                "sources.recovery.baseline.review_required.step.finish_initial_review",
                "sources.recovery.baseline.review_required.step.use_replay_after_review",
            ],
        }

    if active_status in {"PENDING", "QUEUED", "RUNNING"} or guidance_action == "continue_review_with_caution":
        return {
            "trust_state": "partial",
            "impact_summary": _active_sync_summary(provider=provider),
            "impact_code": f"sources.recovery.{provider or 'source'}.active_sync",
            "next_action": "wait",
            "next_action_label": "Wait for sync",
            "last_good_sync_at": _last_good_sync_at(latest_replay_payload=latest_replay_payload, bootstrap_payload=bootstrap_payload),
            "degraded_since": _pick_degraded_since(latest_replay_payload=latest_replay_payload, active_payload=active_payload),
            "recovery_steps": [
                "Current changes can still be reviewed.",
                "Expect more changes to appear after the active sync completes.",
            ],
            "recovery_step_codes": [
                "sources.recovery.active_sync.step.review_current_changes",
                "sources.recovery.active_sync.step.expect_more_after_completion",
            ],
        }

    return {
        "trust_state": "trusted",
        "impact_summary": _trusted_summary(provider=provider),
        "impact_code": f"sources.recovery.{provider or 'source'}.trusted",
        "next_action": "wait",
        "next_action_label": "No action needed",
        "last_good_sync_at": _last_good_sync_at(latest_replay_payload=latest_replay_payload, bootstrap_payload=bootstrap_payload),
        "degraded_since": None,
        "recovery_steps": [],
        "recovery_step_codes": [],
    }


def _trusted_summary(*, provider: str) -> str:
    if provider == "gmail":
        return "This mailbox is connected and contributing to live monitoring."
    if provider == "ics":
        return "This calendar feed is connected and contributing to live monitoring."
    return "This source is connected and contributing to live monitoring."


def _active_sync_summary(*, provider: str) -> str:
    if provider == "gmail":
        return "New Gmail-based changes may still arrive while this sync is running."
    if provider == "ics":
        return "Calendar-backed changes may still update while this sync is running."
    return "New changes may still arrive while this sync is running."


def _runtime_failure_summary(*, provider: str) -> str:
    if provider == "gmail":
        return "The latest Gmail sync failed, so recent email-based changes may be missing."
    if provider == "ics":
        return "The latest Canvas ICS sync failed, so recent calendar changes may be missing."
    return "The latest source sync failed, so recent changes may be missing."


def _runtime_stalled_summary(*, provider: str) -> str:
    if provider == "gmail":
        return "The current Gmail sync has stopped reporting fresh progress, so new email-based changes are not trustworthy yet."
    if provider == "ics":
        return "The current Canvas ICS sync has stopped reporting fresh progress, so new calendar changes are not trustworthy yet."
    return "The current source sync has stopped reporting fresh progress, so new changes are not trustworthy yet."


def _last_good_sync_at(*, latest_replay_payload: dict | None, bootstrap_payload: dict | None) -> datetime | None:
    for payload in (latest_replay_payload, bootstrap_payload):
        if not isinstance(payload, dict):
            continue
        if str(payload.get("status") or "") != "SUCCEEDED":
            continue
        return _coerce_datetime(payload.get("applied_at")) or _coerce_datetime(payload.get("updated_at"))
    return None


def _pick_degraded_since(*, latest_replay_payload: dict | None, active_payload: dict | None) -> datetime | None:
    for payload in (active_payload, latest_replay_payload):
        if not isinstance(payload, dict):
            continue
        return (
            _coerce_datetime(payload.get("stage_updated_at"))
            or _coerce_datetime(payload.get("created_at"))
            or _coerce_datetime(payload.get("updated_at"))
        )
    return None


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
    "build_source_product_phase",
    "build_source_recovery_payload",
]
