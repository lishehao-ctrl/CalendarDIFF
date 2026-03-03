from __future__ import annotations

from fastapi.testclient import TestClient


def test_internal_ingest_ops_requires_service_token(db_engine) -> None:
    del db_engine
    from services.ingest_api.main import app as ingest_app

    endpoint = "/internal/v2/ingest-jobs/999999/replays"
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
