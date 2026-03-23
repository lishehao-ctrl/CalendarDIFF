from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.sources.status_projection import build_source_operator_guidance_payload


def test_guidance_payload_exposes_sync_queued_message_code() -> None:
    payload = build_source_operator_guidance_payload(
        active_payload={
            "status": "QUEUED",
            "stage": "connector_fetch",
            "request_id": "queued-1",
            "progress": {"updated_at": datetime.now(UTC).isoformat()},
        },
        latest_replay_payload=None,
        bootstrap_payload=None,
    )
    assert payload["reason_code"] == "sync_queued"
    assert payload["message_code"] == "sources.operator_guidance.sync_queued"


def test_guidance_payload_exposes_active_sync_failed_message_code() -> None:
    payload = build_source_operator_guidance_payload(
        active_payload={
            "status": "FAILED",
            "stage": "failed",
            "request_id": "failed-1",
            "progress": {"updated_at": datetime.now(UTC).isoformat()},
        },
        latest_replay_payload=None,
        bootstrap_payload=None,
    )
    assert payload["reason_code"] == "active_sync_failed"
    assert payload["message_code"] == "sources.operator_guidance.active_sync_failed"


def test_guidance_payload_exposes_stale_running_message_code() -> None:
    stale = (datetime.now(UTC) - timedelta(seconds=240)).isoformat()
    payload = build_source_operator_guidance_payload(
        active_payload={
            "status": "RUNNING",
            "stage": "provider_reduce",
            "request_id": "stale-1",
            "progress": {"updated_at": stale},
        },
        latest_replay_payload=None,
        bootstrap_payload=None,
    )
    assert payload["reason_code"] == "sync_progress_stale"
    assert payload["message_code"] == "sources.operator_guidance.sync_progress_stale"
