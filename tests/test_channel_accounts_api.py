from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.shared import User
from app.modules.channels.service import create_channel_account, record_channel_delivery


def _create_user(db_session, *, email: str) -> User:
    user = User(
        email=email,
        notify_email=email,
        password_hash="hash",
        timezone_name="America/Los_Angeles",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_settings_channel_accounts_create_list_and_revoke(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="channel-account-user@example.com")
    headers = auth_headers(client, user=user)

    create_response = client.post(
        "/settings/channel-accounts",
        headers=headers,
        json={
            "channel_type": "telegram",
            "account_label": "Personal Telegram",
            "external_user_id": "tg-123",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["channel_type"] == "telegram"
    assert created["status"] == "active"
    assert created["verification_status"] == "pending"

    list_response = client.get("/settings/channel-accounts", headers=headers)
    assert list_response.status_code == 200
    rows = list_response.json()
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]

    revoke_response = client.delete(f"/settings/channel-accounts/{created['id']}", headers=headers)
    assert revoke_response.status_code == 200
    revoked = revoke_response.json()
    assert revoked["status"] == "revoked"
    assert revoked["verification_status"] == "revoked"


def test_settings_channel_deliveries_list_returns_recent_audit_rows(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="channel-delivery-user@example.com")
    account = create_channel_account(
        db_session,
        user=user,
        channel_type="slack",
        account_label="Ops Slack",
        external_user_id="U123",
        external_workspace_id="T456",
    )
    record_channel_delivery(
        db_session,
        user_id=user.id,
        channel_account_id=account.id,
        proposal_id=None,
        ticket_id=None,
        delivery_kind="approval_ticket",
        summary_code="agents.ticket.confirm.change_decision.summary",
        detail_code="agents.ticket.transition.change_decision.waiting_confirm",
        cta_code="agents.ticket.cta.confirm",
        payload_json={"preview": True},
        origin_kind="system",
        origin_label="channel_dispatcher",
    )

    response = client.get("/settings/channel-deliveries", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["delivery_kind"] == "approval_ticket"
    assert payload[0]["summary_code"] == "agents.ticket.confirm.change_decision.summary"
    assert payload[0]["origin_kind"] == "system"
