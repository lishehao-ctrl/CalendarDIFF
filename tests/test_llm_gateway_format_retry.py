from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import BaseModel

import app.modules.llm_gateway.gateway as gateway_module
import app.modules.llm_gateway.route_registry as route_registry_module
from app.modules.llm_gateway.contracts import LlmGatewayError, LlmInvokeRequest, ResolvedLlmProfile
from app.modules.llm_gateway.gateway import LlmGateway
from app.modules.llm_gateway.retry_policy import LLM_FORMAT_MAX_ATTEMPTS
from app.modules.llm_gateway.route_registry import ResolvedLlmRoute
from app.modules.llm_gateway.structured import invoke_llm_typed


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
        vendor="openai",
        protocol="responses",
        base_url="https://example.com/v1",
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
        protocol="responses",
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


class _StrictPayload(BaseModel):
    ok: bool
    count: int


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
        route_registry_module,
        "resolve_llm_profile",
        lambda db, source_id, explicit_provider_id=None, explicit_protocol=None: _profile(),
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
        route_registry_module,
        "resolve_llm_profile",
        lambda db, source_id, explicit_provider_id=None, explicit_protocol=None: _profile(),
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
        route_registry_module,
        "resolve_llm_profile",
        lambda db, source_id, explicit_provider_id=None, explicit_protocol=None: _profile(),
    )

    with pytest.raises(LlmGatewayError) as exc_info:
        gateway.invoke_json(None, invoke_request=_invoke_request())  # type: ignore[arg-type]

    assert exc_info.value.code == "parse_llm_upstream_error"
    assert transport.calls == 1


def test_gateway_switches_base_url_when_protocol_override_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = CapturingTransport()
    gateway = LlmGateway(transport=transport)  # type: ignore[arg-type]
    monkeypatch.setattr(
        route_registry_module,
        "resolve_llm_profile",
        lambda db, source_id, explicit_provider_id=None, explicit_protocol=None: ResolvedLlmProfile(
            provider_id="env-default",
            vendor="dashscope_openai",
            protocol=explicit_protocol or "chat_completions",
            base_url="https://dashscope-us.aliyuncs.com/compatible-mode/v1",
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
        lambda *, protocol, fallback_base_url=None, provider_id=None: (
            "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1"
            if protocol == "responses"
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
            protocol_override="responses",
        ),
    )  # type: ignore[arg-type]

    assert transport.profile is not None
    assert transport.profile.protocol == "responses"
    assert transport.profile.base_url == "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1"


def test_gateway_records_sync_request_usage_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = CapturingTransport()
    gateway = LlmGateway(transport=transport)  # type: ignore[arg-type]
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        route_registry_module,
        "resolve_llm_profile",
        lambda db, source_id, explicit_provider_id=None, explicit_protocol=None: _profile(),
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


def test_invoke_llm_typed_retries_model_validation_until_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_invoke(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        del invoke_request
        calls["count"] += 1
        if calls["count"] < 3:
            return gateway_module.LlmInvokeResult(
                json_object={"ok": True},
                provider_id="env-default",
                protocol="responses",
                model="test-model",
                latency_ms=5,
                response_id=f"resp-{calls['count']}",
                raw_usage={},
            )
        return gateway_module.LlmInvokeResult(
            json_object={"ok": True, "count": 3},
            provider_id="env-default",
            protocol="responses",
            model="test-model",
            latency_ms=5,
            response_id="resp-3",
            raw_usage={},
        )

    monkeypatch.setattr("app.modules.llm_gateway.structured.invoke_llm_json", fake_invoke)

    result = invoke_llm_typed(
        None,  # type: ignore[arg-type]
        invoke_request=_invoke_request(),
        response_model=_StrictPayload,
        validation_label="strict_payload",
    )

    assert isinstance(result.value, _StrictPayload)
    assert result.value.count == 3
    assert calls["count"] == 3


def test_gateway_uses_agent_profile_family_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = CapturingTransport()
    gateway = LlmGateway(transport=transport)  # type: ignore[arg-type]

    monkeypatch.setattr(
        route_registry_module,
        "resolve_agent_llm_profile",
        lambda explicit_protocol=None, explicit_provider_id=None: ResolvedLlmProfile(
            provider_id="agent-env-default",
            vendor="openai",
            protocol=explicit_protocol or "responses",
            base_url="https://agent.example.com/v1",
            model="agent-model",
            api_key="test-key",
            session_cache_enabled=False,
            timeout_seconds=12.0,
            max_retries=0,
            max_input_chars=12000,
        ),
    )
    monkeypatch.setattr(
        route_registry_module,
        "resolve_llm_profile",
        lambda db, source_id, explicit_provider_id=None, explicit_protocol=None: _profile(),
    )

    gateway.invoke_json(
        None,
        invoke_request=LlmInvokeRequest(
            task_name="agent_task",
            system_prompt="Return JSON object only.",
            user_payload={"message": {"subject": "hello"}},
            output_schema_name="AnyObject",
            output_schema_json={"type": "object"},
            profile_family="agent",
            protocol_override="responses",
        ),
    )  # type: ignore[arg-type]

    assert transport.profile is not None
    assert transport.profile.provider_id == "agent-env-default"
    assert transport.profile.model == "agent-model"


def test_gateway_falls_back_to_second_route_on_retryable_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    primary = ResolvedLlmRoute(
        route_id="ingestion:env-default:responses:primary",
        profile=_profile(),
        is_fallback=False,
    )
    fallback = ResolvedLlmRoute(
        route_id="ingestion:env-default:chat_completions:fallback",
        profile=ResolvedLlmProfile(
            provider_id="env-default",
            vendor="openai",
            protocol="chat_completions",
            base_url="https://example.com/v1",
            model="fallback-model",
            api_key="test-key",
            session_cache_enabled=False,
            timeout_seconds=12.0,
            max_retries=0,
            max_input_chars=12000,
        ),
        is_fallback=True,
    )

    class _FallbackTransport:
        def __init__(self) -> None:
            self.calls = 0
            self.profiles: list[ResolvedLlmProfile] = []

        def post_json(self, **kwargs: object) -> tuple[dict, int, str | None]:
            profile = kwargs.get("profile")
            assert isinstance(profile, ResolvedLlmProfile)
            self.profiles.append(profile)
            self.calls += 1
            if self.calls == 1:
                raise _gateway_error(code="parse_llm_upstream_error", retryable=True)
            return (
                {
                    "choices": [
                        {
                            "message": {
                                "content": "{\"ok\":true}",
                            }
                        }
                    ],
                    "usage": {"total_tokens": 1},
                },
                7,
                "upstream-2",
            )

    transport = _FallbackTransport()
    gateway = LlmGateway(transport=transport)  # type: ignore[arg-type]
    monkeypatch.setattr(gateway_module, "resolve_llm_routes", lambda db, invoke_request: [primary, fallback])

    result = gateway.invoke_json(None, invoke_request=_invoke_request())  # type: ignore[arg-type]

    assert result.json_object == {"ok": True}
    assert result.route_id == "ingestion:env-default:chat_completions:fallback"
    assert [profile.protocol for profile in transport.profiles] == ["responses", "chat_completions"]
