from __future__ import annotations

import httpx
import pytest

from app.core.config import get_settings
from app.modules.sync.email_llm_fallback import (
    EmailLlmFallbackClient,
    EmailLlmFallbackError,
    EmailLlmRequestPayload,
)


def _build_payload(body_text: str = "deadline moved to Mar 3 11:59 PM PT") -> EmailLlmRequestPayload:
    return EmailLlmRequestPayload(
        subject="[CSE 100] update",
        snippet="deadline moved",
        body_text=body_text,
        from_header="instructor@school.edu",
        internal_date="2026-02-20T10:00:00+00:00",
        timezone_name="America/Los_Angeles",
        rule_event_type="deadline",
        rule_score=0.0,
    )


def _configure_llm_env(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("EMAIL_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("EMAIL_LLM_BASE_URL", "http://llm.local/v1")
    monkeypatch.setenv("EMAIL_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("EMAIL_LLM_MODEL", "test-model")


def test_llm_fallback_parses_structured_json(monkeypatch) -> None:  # noqa: ANN001
    _configure_llm_env(monkeypatch)
    get_settings.cache_clear()

    client = EmailLlmFallbackClient(settings=get_settings())

    def fake_post(_self, request_payload: dict) -> dict:  # noqa: ANN001
        assert request_payload["response_format"] == {"type": "json_object"}
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"label":"KEEP","event_type":"deadline","confidence":0.93,'
                        '"reasons":["deadline detected"],"raw_extract":{"deadline_text":"Mar 3 11:59 PM PT"},'
                        '"action_items":[{"action":"Review deadline","due_iso":"2026-03-04T07:59:00+00:00"}]}'
                    }
                }
            ]
        }

    monkeypatch.setattr(EmailLlmFallbackClient, "_post_chat_completions", fake_post)
    decision = client.extract_for_ambiguous_email(_build_payload())

    assert decision.label == "KEEP"
    assert decision.event_type == "deadline"
    assert decision.confidence == pytest.approx(0.93)
    assert decision.action_items[0].due_iso == "2026-03-04T07:59:00+00:00"

    get_settings.cache_clear()


def test_llm_fallback_rejects_non_json_content(monkeypatch) -> None:  # noqa: ANN001
    _configure_llm_env(monkeypatch)
    get_settings.cache_clear()

    client = EmailLlmFallbackClient(settings=get_settings())

    def fake_post(_self, _request_payload: dict) -> dict:  # noqa: ANN001
        return {
            "choices": [
                {
                    "message": {
                        "content": "not-json"
                    }
                }
            ]
        }

    monkeypatch.setattr(EmailLlmFallbackClient, "_post_chat_completions", fake_post)

    with pytest.raises(EmailLlmFallbackError) as exc_info:
        client.extract_for_ambiguous_email(_build_payload())

    assert exc_info.value.code == "llm_fallback_invalid_json"
    get_settings.cache_clear()


def test_llm_fallback_rejects_schema_invalid_payload(monkeypatch) -> None:  # noqa: ANN001
    _configure_llm_env(monkeypatch)
    get_settings.cache_clear()

    client = EmailLlmFallbackClient(settings=get_settings())

    def fake_post(_self, _request_payload: dict) -> dict:  # noqa: ANN001
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"label":"KEEP","event_type":"deadline","confidence":"high"}'
                    }
                }
            ]
        }

    monkeypatch.setattr(EmailLlmFallbackClient, "_post_chat_completions", fake_post)

    with pytest.raises(EmailLlmFallbackError) as exc_info:
        client.extract_for_ambiguous_email(_build_payload())

    assert exc_info.value.code == "llm_fallback_schema_invalid"
    get_settings.cache_clear()


def test_llm_fallback_timeout_is_fail_closed(monkeypatch) -> None:  # noqa: ANN001
    _configure_llm_env(monkeypatch)
    monkeypatch.setenv("EMAIL_LLM_MAX_RETRIES", "1")
    get_settings.cache_clear()

    client = EmailLlmFallbackClient(settings=get_settings())

    def fake_post(_self, _request_payload: dict) -> dict:  # noqa: ANN001
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(EmailLlmFallbackClient, "_post_chat_completions", fake_post)

    with pytest.raises(EmailLlmFallbackError) as exc_info:
        client.extract_for_ambiguous_email(_build_payload())

    assert exc_info.value.code == "llm_fallback_timeout"
    get_settings.cache_clear()


def test_llm_fallback_truncates_body_text(monkeypatch) -> None:  # noqa: ANN001
    _configure_llm_env(monkeypatch)
    monkeypatch.setenv("EMAIL_LLM_MAX_BODY_CHARS", "16")
    get_settings.cache_clear()

    client = EmailLlmFallbackClient(settings=get_settings())

    captured: dict[str, object] = {}

    def fake_post(_self, request_payload: dict) -> dict:  # noqa: ANN001
        captured["payload"] = request_payload
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"label":"DROP","event_type":null,"confidence":0.61,"reasons":["unclear"],"raw_extract":{},"action_items":[]}'
                    }
                }
            ]
        }

    monkeypatch.setattr(EmailLlmFallbackClient, "_post_chat_completions", fake_post)
    client.extract_for_ambiguous_email(_build_payload(body_text="x" * 128))

    messages = captured["payload"]["messages"]  # type: ignore[index]
    user_prompt = messages[1]["content"]  # type: ignore[index]
    assert '"body_text": "xxxxxxxxxxxxxxxx"' in user_prompt

    get_settings.cache_clear()
