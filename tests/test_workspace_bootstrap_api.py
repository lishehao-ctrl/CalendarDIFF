from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import User


def test_workspace_bootstrap_requires_api_key(client) -> None:
    response = client.get("/v1/workspace/bootstrap")
    assert response.status_code == 401


def test_workspace_bootstrap_returns_needs_user_without_profile(client) -> None:
    headers = {"X-API-Key": "test-api-key"}
    response = client.get("/v1/workspace/bootstrap", headers=headers)
    assert response.status_code == 200
    payload = response.json()

    assert payload["onboarding"]["stage"] == "needs_user"
    assert payload["user"] is None
    assert payload["inputs"] == []
    assert payload["health_summary"]["db_ok"] is True


def test_workspace_bootstrap_returns_ready_with_inputs(client, initialized_user) -> None:
    del initialized_user
    headers = {"X-API-Key": "test-api-key"}
    response = client.get("/v1/workspace/bootstrap", headers=headers)
    assert response.status_code == 200
    payload = response.json()

    assert payload["onboarding"]["stage"] == "ready"
    assert payload["user"] is not None
    assert payload["user"]["notify_email"] == "student@example.com"
    assert len(payload["inputs"]) >= 1
    assert payload["defaults"]["default_sync_interval_minutes"] == 15
    assert payload["health_summary"]["scheduler_running"] is False


def test_workspace_bootstrap_returns_needs_ics_for_initialized_user_without_ics(client, db_session) -> None:
    user = User(
        email=None,
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()

    headers = {"X-API-Key": "test-api-key"}
    response = client.get("/v1/workspace/bootstrap", headers=headers)
    assert response.status_code == 200
    payload = response.json()

    assert payload["onboarding"]["stage"] == "needs_ics"
    assert payload["inputs"] == []
