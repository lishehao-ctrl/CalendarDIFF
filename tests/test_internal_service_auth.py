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

    monkeypatch.setattr(llm_metrics_module, "get_redis_client", lambda: object())
    monkeypatch.setattr(llm_metrics_module, "queue_depth_stream", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(llm_metrics_module, "queue_depth_retry", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(llm_metrics_module, "read_metric_counter_1m", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(llm_metrics_module, "latency_p95_5m", lambda *_args, **_kwargs: 0.0)

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
