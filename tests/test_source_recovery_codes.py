from __future__ import annotations

from app.modules.sources.recovery_projection import build_source_recovery_payload


def test_gmail_oauth_disconnected_exposes_recovery_codes() -> None:
    payload = build_source_recovery_payload(
        provider="gmail",
        oauth_connection_status="not_connected",
        runtime_state="active",
        operator_guidance=None,
        bootstrap_summary={"state": "completed"},
        active_payload=None,
        latest_replay_payload=None,
        bootstrap_payload=None,
    )
    assert payload["impact_code"] == "sources.recovery.gmail.oauth_disconnected"
    assert payload["next_action"] == "reconnect_gmail"
    assert payload["recovery_step_codes"] == [
        "sources.recovery.gmail.step.reconnect_mailbox",
        "sources.recovery.gmail.step.wait_for_sync",
    ]


def test_active_sync_exposes_sync_wait_codes() -> None:
    payload = build_source_recovery_payload(
        provider="ics",
        oauth_connection_status=None,
        runtime_state="running",
        operator_guidance={"recommended_action": "continue_review_with_caution", "severity": "warning"},
        bootstrap_summary={"state": "completed"},
        active_payload={"status": "RUNNING"},
        latest_replay_payload=None,
        bootstrap_payload=None,
    )
    assert payload["impact_code"] == "sources.recovery.ics.active_sync"
    assert payload["next_action"] == "wait"
    assert payload["recovery_step_codes"] == [
        "sources.recovery.active_sync.step.review_current_changes",
        "sources.recovery.active_sync.step.expect_more_after_completion",
    ]
