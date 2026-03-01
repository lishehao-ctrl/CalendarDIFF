from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import User


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-api-key"}


def _ensure_user(db_session: Session) -> User:
    user = User(
        email=None,
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_internal_llm_provider_crud_and_default(client: TestClient) -> None:
    create_payload = {
        "provider_id": "openai_main",
        "name": "OpenAI Main",
        "vendor": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_mode": "chat_completions",
        "model": "gpt-5.3-codex",
        "api_key_ref": "OPENAI_MAIN_KEY",
        "timeout_seconds": 12.0,
        "max_retries": 1,
        "max_input_chars": 12000,
        "enabled": True,
        "is_default": False,
        "extra_config": {"purpose": "test"},
    }
    create_resp = client.post("/internal/v2/llm-providers", headers=_auth_headers(), json=create_payload)
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["provider_id"] == "openai_main"
    assert body["api_mode"] == "chat_completions"
    assert body["is_default"] is False

    list_resp = client.get("/internal/v2/llm-providers", headers=_auth_headers())
    assert list_resp.status_code == 200
    assert any(row["provider_id"] == "openai_main" for row in list_resp.json())

    default_resp = client.post(
        "/internal/v2/llm-default-provider",
        headers=_auth_headers(),
        json={"provider_id": "openai_main"},
    )
    assert default_resp.status_code == 200
    assert default_resp.json()["is_default"] is True


def test_input_source_create_supports_llm_binding(client: TestClient, db_session: Session) -> None:
    _ensure_user(db_session)
    provider_payload = {
        "provider_id": "deepseek_main",
        "name": "DeepSeek Main",
        "vendor": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "api_mode": "responses",
        "model": "deepseek-chat",
        "api_key_ref": "DEEPSEEK_MAIN_KEY",
        "enabled": True,
        "is_default": True,
    }
    provider_resp = client.post("/internal/v2/llm-providers", headers=_auth_headers(), json=provider_payload)
    assert provider_resp.status_code == 201

    source_payload = {
        "source_kind": "calendar",
        "provider": "ics",
        "source_key": "calendar-with-llm-binding",
        "display_name": "Calendar Source",
        "poll_interval_seconds": 900,
        "config": {},
        "secrets": {"url": "https://example.com/courses.ics"},
        "llm_binding": {
            "provider_id": "deepseek_main",
            "model_override": "deepseek-reasoner",
            "api_mode_override": "responses",
            "prompt_profile": "academic_calendar",
            "enabled": True,
        },
    }
    create_resp = client.post("/v2/input-sources", headers=_auth_headers(), json=source_payload)
    assert create_resp.status_code == 201
    payload = create_resp.json()
    assert payload["llm_binding"]["provider_id"] == "deepseek_main"
    assert payload["llm_binding"]["model"] == "deepseek-reasoner"
    assert payload["llm_binding"]["api_mode"] == "responses"
