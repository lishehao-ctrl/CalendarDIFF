from __future__ import annotations

from datetime import UTC, datetime

from app.modules.common.structured_copy import render_structured_list, render_structured_text


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
    language_code: str | None = None,
) -> dict:
    bootstrap_state = str((bootstrap_summary or {}).get("state") or "")
    active_status = str((active_payload or {}).get("status") or "")
    latest_replay_status = str((latest_replay_payload or {}).get("status") or "")
    guidance_action = str((operator_guidance or {}).get("recommended_action") or "")
    guidance_severity = str((operator_guidance or {}).get("severity") or "")
    last_good_sync_at = _last_good_sync_at(latest_replay_payload=latest_replay_payload, bootstrap_payload=bootstrap_payload)
    degraded_since = _pick_degraded_since(latest_replay_payload=latest_replay_payload, active_payload=active_payload)

    if provider == "gmail" and oauth_connection_status == "not_connected":
        impact_code = "sources.recovery.gmail.oauth_disconnected"
        recovery_step_codes = [
            "sources.recovery.gmail.step.reconnect_mailbox",
            "sources.recovery.gmail.step.wait_for_sync",
        ]
        return {
            "trust_state": "blocked",
            "impact_summary": render_structured_text(
                code=impact_code,
                language_code=language_code,
                fallback="New Gmail-based changes may be missing until the mailbox is reconnected.",
            ),
            "impact_code": impact_code,
            "next_action": "reconnect_gmail",
            "next_action_label": render_structured_text(
                code="sources.recovery.next_action.reconnect_gmail",
                language_code=language_code,
                fallback="Reconnect Gmail",
            ),
            "last_good_sync_at": last_good_sync_at,
            "degraded_since": degraded_since,
            "recovery_steps": render_structured_list(
                codes=recovery_step_codes,
                language_code=language_code,
                fallback_items=[
                    "Reconnect the mailbox to restore intake.",
                    "Wait for the next sync to finish before trusting new email-backed changes.",
                ],
            ),
            "recovery_step_codes": recovery_step_codes,
        }

    if runtime_state == "rebind_pending" and provider == "ics":
        impact_code = "sources.recovery.ics.rebind_pending"
        recovery_step_codes = [
            "sources.recovery.ics.step.confirm_feed_settings",
            "sources.recovery.ics.step.run_sync_after_update",
        ]
        return {
            "trust_state": "blocked",
            "impact_summary": render_structured_text(
                code=impact_code,
                language_code=language_code,
                fallback="Canvas ICS needs updated monitoring settings before new calendar updates can be trusted.",
            ),
            "impact_code": impact_code,
            "next_action": "update_ics",
            "next_action_label": render_structured_text(
                code="sources.recovery.next_action.update_ics",
                language_code=language_code,
                fallback="Update Canvas ICS",
            ),
            "last_good_sync_at": last_good_sync_at,
            "degraded_since": degraded_since,
            "recovery_steps": render_structured_list(
                codes=recovery_step_codes,
                language_code=language_code,
                fallback_items=[
                    "Open the Canvas ICS connection flow and confirm the current feed settings.",
                    "Run another sync after saving the updated link.",
                ],
            ),
            "recovery_step_codes": recovery_step_codes,
        }

    if guidance_action == "investigate_runtime" or latest_replay_status == "FAILED":
        impact_code = f"sources.recovery.{provider or 'source'}.runtime_failed"
        recovery_step_codes = [
            "sources.recovery.runtime_failed.step.retry_sync",
            "sources.recovery.runtime_failed.step.investigate_if_repeat",
        ]
        return {
            "trust_state": "stale",
            "impact_summary": render_structured_text(
                code=impact_code,
                language_code=language_code,
                fallback=_runtime_failure_summary(provider=provider),
            ),
            "impact_code": impact_code,
            "next_action": "retry_sync",
            "next_action_label": render_structured_text(
                code="sources.recovery.next_action.retry_sync",
                language_code=language_code,
                fallback="Retry sync",
            ),
            "last_good_sync_at": last_good_sync_at,
            "degraded_since": degraded_since,
            "recovery_steps": render_structured_list(
                codes=recovery_step_codes,
                language_code=language_code,
                fallback_items=[
                    "Retry the source sync.",
                    "If the next sync also fails, investigate the source connection before trusting new changes.",
                ],
            ),
            "recovery_step_codes": recovery_step_codes,
        }

    if guidance_action == "wait_for_runtime" and guidance_severity == "blocking":
        impact_code = f"sources.recovery.{provider or 'source'}.runtime_stalled"
        recovery_step_codes = [
            "sources.recovery.runtime_stalled.step.wait",
            "sources.recovery.runtime_stalled.step.resume_after_progress",
        ]
        return {
            "trust_state": "blocked",
            "impact_summary": render_structured_text(
                code=impact_code,
                language_code=language_code,
                fallback=_runtime_stalled_summary(provider=provider),
            ),
            "impact_code": impact_code,
            "next_action": "wait",
            "next_action_label": render_structured_text(
                code="sources.recovery.next_action.wait_for_runtime",
                language_code=language_code,
                fallback="Wait for runtime",
            ),
            "last_good_sync_at": last_good_sync_at,
            "degraded_since": degraded_since,
            "recovery_steps": render_structured_list(
                codes=recovery_step_codes,
                language_code=language_code,
                fallback_items=[
                    "Let the current runtime work finish or recover.",
                    "Only trust new changes after progress starts moving again or the sync completes.",
                ],
            ),
            "recovery_step_codes": recovery_step_codes,
        }

    if bootstrap_state == "running":
        impact_code = "sources.recovery.baseline.running"
        recovery_step_codes = [
            "sources.recovery.baseline.running.step.wait",
            "sources.recovery.baseline.running.step.review_after_import",
        ]
        return {
            "trust_state": "partial",
            "impact_summary": render_structured_text(
                code=impact_code,
                language_code=language_code,
                fallback="Baseline import is still building this source before steady-state monitoring begins.",
            ),
            "impact_code": impact_code,
            "next_action": "wait",
            "next_action_label": render_structured_text(
                code="sources.recovery.next_action.wait_for_baseline",
                language_code=language_code,
                fallback="Wait for baseline import",
            ),
            "last_good_sync_at": last_good_sync_at,
            "degraded_since": degraded_since,
            "recovery_steps": render_structured_list(
                codes=recovery_step_codes,
                language_code=language_code,
                fallback_items=[
                    "Wait for the initial import to complete.",
                    "Review any baseline items before treating this source as fully live.",
                ],
            ),
            "recovery_step_codes": recovery_step_codes,
        }

    if bootstrap_state == "review_required":
        impact_code = "sources.recovery.baseline.review_required"
        recovery_step_codes = [
            "sources.recovery.baseline.review_required.step.finish_initial_review",
            "sources.recovery.baseline.review_required.step.use_replay_after_review",
        ]
        return {
            "trust_state": "partial",
            "impact_summary": render_structured_text(
                code=impact_code,
                language_code=language_code,
                fallback="Baseline import finished, but Initial Review still has items waiting before this source is fully trusted.",
            ),
            "impact_code": impact_code,
            "next_action": "wait",
            "next_action_label": render_structured_text(
                code="sources.recovery.next_action.finish_initial_review",
                language_code=language_code,
                fallback="Finish Initial Review",
            ),
            "last_good_sync_at": last_good_sync_at,
            "degraded_since": degraded_since,
            "recovery_steps": render_structured_list(
                codes=recovery_step_codes,
                language_code=language_code,
                fallback_items=[
                    "Finish Initial Review for this source.",
                    "After that, use Replay Review for day-to-day change handling.",
                ],
            ),
            "recovery_step_codes": recovery_step_codes,
        }

    if active_status in {"PENDING", "QUEUED", "RUNNING"} or guidance_action == "continue_review_with_caution":
        impact_code = f"sources.recovery.{provider or 'source'}.active_sync"
        recovery_step_codes = [
            "sources.recovery.active_sync.step.review_current_changes",
            "sources.recovery.active_sync.step.expect_more_after_completion",
        ]
        return {
            "trust_state": "partial",
            "impact_summary": render_structured_text(
                code=impact_code,
                language_code=language_code,
                fallback=_active_sync_summary(provider=provider),
            ),
            "impact_code": impact_code,
            "next_action": "wait",
            "next_action_label": render_structured_text(
                code="sources.recovery.next_action.wait_for_sync",
                language_code=language_code,
                fallback="Wait for sync",
            ),
            "last_good_sync_at": last_good_sync_at,
            "degraded_since": degraded_since,
            "recovery_steps": render_structured_list(
                codes=recovery_step_codes,
                language_code=language_code,
                fallback_items=[
                    "Current changes can still be reviewed.",
                    "Expect more changes to appear after the active sync completes.",
                ],
            ),
            "recovery_step_codes": recovery_step_codes,
        }

    impact_code = f"sources.recovery.{provider or 'source'}.trusted"
    return {
        "trust_state": "trusted",
        "impact_summary": render_structured_text(
            code=impact_code,
            language_code=language_code,
            fallback=_trusted_summary(provider=provider),
        ),
        "impact_code": impact_code,
        "next_action": "wait",
        "next_action_label": render_structured_text(
            code="sources.recovery.next_action.none",
            language_code=language_code,
            fallback="No action needed",
        ),
        "last_good_sync_at": last_good_sync_at,
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
