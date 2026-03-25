from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.shared import User


def _create_user(db_session, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="hash",
        timezone_name="America/Los_Angeles",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_settings_mcp_tokens_create_list_and_revoke(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="mcp-token-user@example.com")
    headers = auth_headers(client, user=user)

    create_response = client.post(
        "/settings/mcp-tokens",
        headers=headers,
        json={"label": "QClaw", "expires_in_days": 30},
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["label"] == "QClaw"
    assert created["token"].startswith("cdmcp_")
    assert created["revoked_at"] is None

    list_response = client.get("/settings/mcp-tokens", headers=headers)
    assert list_response.status_code == 200
    rows = list_response.json()
    assert len(rows) == 1
    assert rows[0]["token_id"] == created["token_id"]
    assert rows[0]["label"] == "QClaw"
    assert "token" not in rows[0]

    revoke_response = client.delete(f"/settings/mcp-tokens/{created['token_id']}", headers=headers)
    assert revoke_response.status_code == 200
    revoked = revoke_response.json()
    assert revoked["token_id"] == created["token_id"]
    assert revoked["revoked_at"] is not None

    list_after_revoke = client.get("/settings/mcp-tokens", headers=headers)
    assert list_after_revoke.status_code == 200
    assert list_after_revoke.json()[0]["revoked_at"] is not None
