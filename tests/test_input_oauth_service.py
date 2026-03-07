from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from app.core.security import decrypt_secret, encrypt_secret
from app.db.models.input import InputSourceCursor, InputSourceSecret
from app.db.models.shared import User
from app.modules.input_control_plane.oauth_service import handle_gmail_oauth_callback
from app.modules.input_control_plane.schemas import InputSourceCreateRequest
from app.modules.input_control_plane.sources_service import create_input_source
from app.modules.sync.gmail_client import GmailOAuthTokens


class _FakeGmailClient:
    def exchange_code(self, *, code: str) -> GmailOAuthTokens:
        assert code == "oauth-code"
        return GmailOAuthTokens(
            access_token="new-access-token",
            refresh_token=None,
            expires_at=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
        )

    def get_profile(self, *, access_token: str):
        assert access_token == "new-access-token"
        return SimpleNamespace(email_address="student@example.edu", history_id="200")


def test_oauth_callback_preserves_existing_refresh_token_and_reactivates_source(db_session) -> None:
    user = User(
        email=None,
        notify_email="gmail-owner@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    source = create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="email",
            provider="gmail",
            display_name="Gmail Inbox",
            config={"label_id": "INBOX"},
            secrets={},
        ),
    )
    source.is_active = False
    source.next_poll_at = None
    source.last_error_code = "gmail_auth_failed"
    source.last_error_message = "expired token"
    source.secrets = InputSourceSecret(
        source_id=source.id,
        encrypted_payload=encrypt_secret(
            json.dumps(
                {
                    "access_token": "old-access-token",
                    "refresh_token": "persist-me",
                    "account_email": "student@example.edu",
                    "history_id": "100",
                }
            )
        ),
    )
    source.cursor = InputSourceCursor(source_id=source.id, version=1, cursor_json={"history_id": "100"})
    db_session.commit()

    state_payload = encrypt_secret(
        json.dumps(
            {
                "source_id": source.id,
                "provider": "gmail",
                "exp": datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc).isoformat(),
            }
        )
    )

    refreshed_source, sync_request = handle_gmail_oauth_callback(
        db_session,
        code="oauth-code",
        state=state_payload,
        now=datetime(2026, 3, 6, 11, 0, tzinfo=timezone.utc),
        gmail_client=_FakeGmailClient(),
    )

    merged_payload = json.loads(decrypt_secret(refreshed_source.secrets.encrypted_payload))
    assert merged_payload["access_token"] == "new-access-token"
    assert merged_payload["refresh_token"] == "persist-me"
    assert merged_payload["account_email"] == "student@example.edu"
    assert merged_payload["history_id"] == "200"
    assert refreshed_source.is_active is True
    assert refreshed_source.next_poll_at == datetime(2026, 3, 6, 11, 0, tzinfo=timezone.utc)
    assert refreshed_source.last_error_code is None
    assert refreshed_source.last_error_message is None
    assert refreshed_source.cursor.cursor_json == {"history_id": "200"}
    assert sync_request.request_id
