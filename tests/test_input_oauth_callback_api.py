from __future__ import annotations

from types import SimpleNamespace

import app.modules.input_control_plane.oauth_router as oauth_router


def test_oauth_callback_success_returns_json(input_client, monkeypatch) -> None:
    def _fake_handle(_db, *, code: str, state: str):
        assert code == "oauth-code"
        assert state == "oauth-state"
        source = SimpleNamespace(id=42)
        sync_request = SimpleNamespace(request_id="sync-req-1", status=SimpleNamespace(value="QUEUED"))
        return source, sync_request

    monkeypatch.setattr(oauth_router, "handle_gmail_oauth_callback", _fake_handle)

    response = input_client.get(
        "/oauth/callbacks/gmail",
        params={"code": "oauth-code", "state": "oauth-state"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "source_id": 42,
        "provider": "gmail",
        "request_id": "sync-req-1",
        "status": "success",
        "sync_request_status": "QUEUED",
        "message": "oauth callback processed",
    }


def test_oauth_callback_unsupported_provider_returns_error(input_client) -> None:
    response = input_client.get(
        "/oauth/callbacks/ics",
        params={"code": "oauth-code", "state": "oauth-state"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "source_id": None,
        "provider": "ics",
        "request_id": None,
        "status": "error",
        "sync_request_status": None,
        "message": "unsupported oauth provider",
    }
