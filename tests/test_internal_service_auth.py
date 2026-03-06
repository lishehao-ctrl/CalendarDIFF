from __future__ import annotations

from fastapi.testclient import TestClient


def test_internal_ingest_ops_requires_service_token(db_engine) -> None:
    del db_engine
    from services.ingest_api.main import app as ingest_app

    endpoint = "/internal/ingest/jobs/999999/replays"
    with TestClient(ingest_app) as client:
        unauthorized = client.post(endpoint)
        assert unauthorized.status_code == 401

        wrong_token = client.post(
            endpoint,
            headers={"X-Service-Name": "ops", "X-Service-Token": "wrong"},
        )
        assert wrong_token.status_code == 401

        wrong_caller = client.post(
            endpoint,
            headers={"X-Service-Name": "review", "X-Service-Token": "test-internal-token-review"},
        )
        assert wrong_caller.status_code == 403

        accepted = client.post(
            endpoint,
            headers={"X-Service-Name": "ops", "X-Service-Token": "test-internal-token-ops"},
        )
        assert accepted.status_code == 404


def test_internal_llm_metrics_requires_service_token(db_engine, monkeypatch) -> None:
    del db_engine
    import app.modules.llm_runtime.metrics_router as llm_metrics_module
    from services.llm_api.main import app as llm_app

    monkeypatch.setattr(llm_metrics_module, "get_parse_queue_redis_client", lambda: object())
    monkeypatch.setattr(llm_metrics_module, "parse_queue_depth", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(llm_metrics_module, "parse_retry_depth", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(llm_metrics_module, "read_parse_metric_counter_1m", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(llm_metrics_module, "parse_latency_p95_5m", lambda *_args, **_kwargs: 0.0)

    endpoint = "/internal/metrics"
    with TestClient(llm_app) as client:
        unauthorized = client.get(endpoint)
        assert unauthorized.status_code == 401

        wrong_token = client.get(
            endpoint,
            headers={"X-Service-Name": "ops", "X-Service-Token": "wrong"},
        )
        assert wrong_token.status_code == 401

        wrong_caller = client.get(
            endpoint,
            headers={"X-Service-Name": "review", "X-Service-Token": "test-internal-token-review"},
        )
        assert wrong_caller.status_code == 403

        accepted_ops = client.get(
            endpoint,
            headers={"X-Service-Name": "ops", "X-Service-Token": "test-internal-token-ops"},
        )
        assert accepted_ops.status_code == 200

        accepted_llm = client.get(
            endpoint,
            headers={"X-Service-Name": "llm", "X-Service-Token": "test-internal-token-llm"},
        )
        assert accepted_llm.status_code == 200


def test_internal_notification_flush_requires_service_token(db_engine) -> None:
    del db_engine
    from services.notification_api.main import app as notification_app

    endpoint = "/internal/notifications/flush"
    with TestClient(notification_app) as client:
        unauthorized = client.post(endpoint, json={})
        assert unauthorized.status_code == 401

        wrong_token = client.post(
            endpoint,
            headers={"X-Service-Name": "ops", "X-Service-Token": "wrong"},
            json={},
        )
        assert wrong_token.status_code == 401

        wrong_caller = client.post(
            endpoint,
            headers={"X-Service-Name": "review", "X-Service-Token": "test-internal-token-review"},
            json={},
        )
        assert wrong_caller.status_code == 403

        accepted = client.post(
            endpoint,
            headers={"X-Service-Name": "ops", "X-Service-Token": "test-internal-token-ops"},
            json={},
        )
        assert accepted.status_code == 200
