from __future__ import annotations

from dataclasses import dataclass

import pytest

import app.modules.llm_gateway.gateway as gateway_module
from app.modules.llm_gateway.contracts import LlmGatewayError, LlmInvokeRequest, ResolvedLlmProfile
from app.modules.llm_gateway.gateway import LlmGateway
from app.modules.llm_gateway.retry_policy import LLM_FORMAT_MAX_ATTEMPTS


@dataclass
class SequencedTransport:
    outcomes: list[object]
    calls: int = 0

    def post_json(self, **_: object) -> tuple[dict, int, str | None]:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, tuple)
        return outcome  # type: ignore[return-value]


def _profile() -> ResolvedLlmProfile:
    return ResolvedLlmProfile(
        provider_id="env-default",
        vendor="openai-compatible",
        base_url="https://example.com/v1",
        api_mode="responses",
        model="test-model",
        api_key="test-key",
        session_cache_enabled=False,
        timeout_seconds=12.0,
        max_retries=0,
        max_input_chars=12000,
    )


def _invoke_request() -> LlmInvokeRequest:
    return LlmInvokeRequest(
        task_name="gmail_message_extract",
        system_prompt="Return JSON object only.",
        user_payload={"message": {"subject": "hello"}},
        output_schema_name="AnyObject",
        output_schema_json={"type": "object"},
        source_id=1,
        request_id="req-1",
        source_provider="gmail",
    )


def _gateway_error(*, code: str, retryable: bool = False) -> LlmGatewayError:
    return LlmGatewayError(
        code=code,
        message=code,
        retryable=retryable,
        provider_id="env-default",
        api_mode="responses",
    )


def _success_response() -> tuple[dict, int, str | None]:
    return (
        {
            "output": [
                {
                    "id": "rs_1",
                    "type": "reasoning",
                    "summary": [],
                },
                {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "{\"ok\":true}", "annotations": []}],
                }
            ],
            "usage": {"total_tokens": 1},
        },
        5,
        "upstream-1",
    )


@dataclass
class CapturingTransport:
    profile: ResolvedLlmProfile | None = None

    def post_json(self, **kwargs: object) -> tuple[dict, int, str | None]:
        profile = kwargs.get("profile")
        assert isinstance(profile, ResolvedLlmProfile)
        self.profile = profile
        return _success_response()


def test_gateway_retries_schema_invalid_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = SequencedTransport(
        outcomes=[
            _gateway_error(code="parse_llm_schema_invalid"),
            _gateway_error(code="parse_llm_schema_invalid"),
            _success_response(),
        ]
    )
    gateway = LlmGateway(transport=transport)  # type: ignore[arg-type]
    monkeypatch.setattr(
        gateway_module,
        "resolve_llm_profile",
        lambda db, source_id, explicit_api_mode=None: _profile(),
    )

    result = gateway.invoke_json(None, invoke_request=_invoke_request())  # type: ignore[arg-type]

    assert result.json_object == {"ok": True}
    assert transport.calls == 3


def test_gateway_retries_empty_output_until_max_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = SequencedTransport(
        outcomes=[_gateway_error(code="parse_llm_empty_output")] * LLM_FORMAT_MAX_ATTEMPTS
    )
    gateway = LlmGateway(transport=transport)  # type: ignore[arg-type]
    monkeypatch.setattr(
        gateway_module,
        "resolve_llm_profile",
        lambda db, source_id, explicit_api_mode=None: _profile(),
    )

    with pytest.raises(LlmGatewayError) as exc_info:
        gateway.invoke_json(None, invoke_request=_invoke_request())  # type: ignore[arg-type]

    assert exc_info.value.code == "parse_llm_empty_output"
    assert transport.calls == LLM_FORMAT_MAX_ATTEMPTS


def test_gateway_does_not_retry_non_format_error(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = SequencedTransport(
        outcomes=[_gateway_error(code="parse_llm_upstream_error", retryable=True)]
    )
    gateway = LlmGateway(transport=transport)  # type: ignore[arg-type]
    monkeypatch.setattr(
        gateway_module,
        "resolve_llm_profile",
        lambda db, source_id, explicit_api_mode=None: _profile(),
    )

    with pytest.raises(LlmGatewayError) as exc_info:
        gateway.invoke_json(None, invoke_request=_invoke_request())  # type: ignore[arg-type]

    assert exc_info.value.code == "parse_llm_upstream_error"
    assert transport.calls == 1


def test_gateway_switches_base_url_when_api_mode_override_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = CapturingTransport()
    gateway = LlmGateway(transport=transport)  # type: ignore[arg-type]
    monkeypatch.setattr(
        gateway_module,
        "resolve_llm_profile",
        lambda db, source_id, explicit_api_mode=None: ResolvedLlmProfile(
            provider_id="env-default",
            vendor="openai-compatible",
            base_url="https://dashscope-us.aliyuncs.com/compatible-mode/v1",
            api_mode=explicit_api_mode or "chat_completions",
            model="test-model",
            api_key="test-key",
            session_cache_enabled=False,
            timeout_seconds=12.0,
            max_retries=0,
            max_input_chars=12000,
        ),
    )
    monkeypatch.setattr(
        gateway_module,
        "resolve_llm_base_url",
        lambda *, api_mode, fallback_base_url=None: (
            "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1"
            if api_mode == "responses"
            else "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
        ),
    )

    gateway.invoke_json(
        None,
        invoke_request=LlmInvokeRequest(
            task_name="gmail_message_extract",
            system_prompt="Return JSON object only.",
            user_payload={"message": {"subject": "hello"}},
            output_schema_name="AnyObject",
            output_schema_json={"type": "object"},
            source_id=1,
            request_id="req-1",
            source_provider="gmail",
            api_mode_override="responses",
        ),
    )  # type: ignore[arg-type]

    assert transport.profile is not None
    assert transport.profile.api_mode == "responses"
    assert transport.profile.base_url == "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1"


def test_gateway_records_sync_request_usage_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = CapturingTransport()
    gateway = LlmGateway(transport=transport)  # type: ignore[arg-type]
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        gateway_module,
        "resolve_llm_profile",
        lambda db, source_id, explicit_api_mode=None: _profile(),
    )
    monkeypatch.setattr(
        gateway_module,
        "record_sync_request_llm_usage",
        lambda *, invoke_request, result: captured.update({"invoke_request": invoke_request, "result": result}),
    )

    result = gateway.invoke_json(None, invoke_request=_invoke_request())  # type: ignore[arg-type]

    assert result.json_object == {"ok": True}
    assert captured["invoke_request"] == _invoke_request()
    assert captured["result"] == result
