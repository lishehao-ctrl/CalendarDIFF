from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _assert_metrics_payload(payload: dict, *, service_name: str, keys: Sequence[str]) -> None:
    assert payload["service_name"] == service_name
    assert isinstance(payload["timestamp"], str) and payload["timestamp"]
    metrics = payload.get("metrics")
    assert isinstance(metrics, dict)
    for key in keys:
        assert key in metrics
        assert isinstance(metrics[key], (int, float))


def _call_metrics(app: FastAPI) -> dict:
    headers = {"X-Service-Name": "ops", "X-Service-Token": "test-internal-token-ops"}
    with TestClient(app) as client:
        response = client.get("/internal/v2/metrics", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def test_internal_metrics_endpoints(db_engine, monkeypatch) -> None:
    del db_engine
    import app.modules.llm_runtime.metrics_router as llm_metrics_module
    from services.ingest_api.main import app as ingest_app
    from services.input_api.main import app as input_app
    from services.llm_api.main import app as llm_app
    from services.notification_api.main import app as notify_app
    from services.review_api.main import app as review_app

    monkeypatch.setattr(llm_metrics_module, "get_redis_client", lambda: object())
    monkeypatch.setattr(llm_metrics_module, "queue_depth_stream", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(llm_metrics_module, "queue_depth_retry", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(llm_metrics_module, "read_metric_counter_1m", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(llm_metrics_module, "latency_p95_5m", lambda *_args, **_kwargs: 0.0)

    input_payload = _call_metrics(input_app)
    _assert_metrics_payload(
        input_payload,
        service_name="input-service",
        keys=["active_sources", "due_sources", "sync_requests_pending", "sync_requests_failed_1h"],
    )

    ingest_payload = _call_metrics(ingest_app)
    _assert_metrics_payload(
        ingest_payload,
        service_name="ingest-service",
        keys=[
            "ingest_jobs_pending",
            "ingest_jobs_dead_letter",
            "dead_letter_rate_1h",
            "event_lag_seconds_p95",
            "source_fifo_deferred_count_1m",
            "llm_rate_limited_1h",
            "llm_retry_scheduled_1h",
            "ics_delta_components_total_1m",
            "ics_delta_changed_components_1m",
            "ics_delta_removed_components_1m",
            "ics_delta_parse_failures_1h",
        ],
    )

    review_payload = _call_metrics(review_app)
    _assert_metrics_payload(
        review_payload,
        service_name="review-service",
        keys=[
            "pending_changes",
            "pending_backlog_age_seconds_max",
            "apply_queue_pending",
            "linker_auto_link_total",
            "linker_candidate_total",
            "linker_unlinked_total",
            "linker_block_hit_total",
            "linker_candidate_decision_approve_total",
            "linker_candidate_decision_reject_total",
            "linker_false_link_corrections_total",
        ],
    )

    notify_payload = _call_metrics(notify_app)
    _assert_metrics_payload(
        notify_payload,
        service_name="notification-service",
        keys=["notifications_pending", "digest_sent_24h", "digest_failed_24h", "notify_fail_rate_24h"],
    )

    llm_payload = _call_metrics(llm_app)
    _assert_metrics_payload(
        llm_payload,
        service_name="llm-service",
        keys=[
            "queue_depth_stream",
            "queue_depth_retry",
            "llm_calls_total_1m",
            "llm_calls_rate_limited_1m",
            "llm_call_latency_ms_p95_5m",
            "limiter_reject_rate_1m",
        ],
    )
