from __future__ import annotations


def test_health_returns_scheduler_summary(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()

    assert "db" in payload
    assert "scheduler" in payload
    assert "running" in payload["scheduler"]
    assert "last_run_started_at" in payload["scheduler"]
