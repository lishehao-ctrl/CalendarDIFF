from __future__ import annotations

from app.modules.common.api_errors import api_error_detail


def test_api_error_detail_builds_default_message_code() -> None:
    payload = api_error_detail(code="auth.invalid_credentials", message="invalid credentials")
    assert payload == {
        "code": "auth.invalid_credentials",
        "message": "invalid credentials",
        "message_code": "auth.invalid_credentials",
        "message_params": {},
    }


def test_api_error_detail_preserves_extra_fields() -> None:
    payload = api_error_detail(
        code="gmail_source_exists",
        message="gmail source already exists for this user",
        message_code="sources.create.gmail_source_exists",
        existing_source_id=12,
    )
    assert payload["message_code"] == "sources.create.gmail_source_exists"
    assert payload["existing_source_id"] == 12
