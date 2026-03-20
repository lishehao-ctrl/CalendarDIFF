from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from app.core.config import get_settings
import app.modules.sources.oauth_router as oauth_router


def test_oauth_callback_success_redirects_to_frontend(input_client, monkeypatch) -> None:
    monkeypatch.setenv("FRONTEND_APP_BASE_URL", "http://127.0.0.1:3000")
    get_settings.cache_clear()

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
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    parsed = urlparse(location)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "http://127.0.0.1:3000/sources"
    query = parse_qs(parsed.query)
    assert query == {
        "oauth_provider": ["gmail"],
        "oauth_status": ["success"],
        "source_id": ["42"],
        "request_id": ["sync-req-1"],
        "message": ["oauth callback processed"],
    }
    get_settings.cache_clear()


def test_oauth_callback_json_format_returns_json(input_client, monkeypatch) -> None:
    def _fake_handle(_db, *, code: str, state: str):
        assert code == "oauth-code"
        assert state == "oauth-state"
        source = SimpleNamespace(id=42)
        sync_request = SimpleNamespace(request_id="sync-req-1", status=SimpleNamespace(value="QUEUED"))
        return source, sync_request

    monkeypatch.setattr(oauth_router, "handle_gmail_oauth_callback", _fake_handle)

    response = input_client.get(
        "/oauth/callbacks/gmail",
        params={"code": "oauth-code", "state": "oauth-state", "format": "json"},
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


def test_oauth_callback_accept_json_returns_json(input_client, monkeypatch) -> None:
    def _fake_handle(_db, *, code: str, state: str):
        source = SimpleNamespace(id=21)
        sync_request = SimpleNamespace(request_id="sync-req-9", status=SimpleNamespace(value="QUEUED"))
        return source, sync_request

    monkeypatch.setattr(oauth_router, "handle_gmail_oauth_callback", _fake_handle)

    response = input_client.get(
        "/oauth/callbacks/gmail",
        params={"code": "oauth-code", "state": "oauth-state"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["source_id"] == 21
    assert response.json()["status"] == "success"


def test_oauth_callback_unsupported_provider_redirects_error(input_client, monkeypatch) -> None:
    monkeypatch.setenv("FRONTEND_APP_BASE_URL", "http://127.0.0.1:3000")
    get_settings.cache_clear()

    response = input_client.get(
        "/oauth/callbacks/ics",
        params={"code": "oauth-code", "state": "oauth-state"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    parsed = urlparse(response.headers["location"])
    query = parse_qs(parsed.query)
    assert query["oauth_provider"] == ["ics"]
    assert query["oauth_status"] == ["error"]
    assert query["message"] == ["unsupported oauth provider"]
    get_settings.cache_clear()
