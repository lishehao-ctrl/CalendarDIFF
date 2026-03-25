from __future__ import annotations

from app.modules.llm_gateway.adapters.chat_completions import build_chat_completions_payload
from app.modules.llm_gateway.adapters.responses import build_responses_payload
from app.modules.llm_gateway.contracts import LlmInvokeRequest, ResolvedLlmProfile
from app.modules.llm_gateway.transport_openai_compat import OpenAICompatTransport


def _profile(*, session_cache_enabled: bool, vendor: str = "openai", protocol: str = "responses") -> ResolvedLlmProfile:
    return ResolvedLlmProfile(
        provider_id="env-default",
        vendor=vendor,  # type: ignore[arg-type]
        protocol=protocol,  # type: ignore[arg-type]
        base_url="https://example.com/v1",
        model="test-model",
        api_key="test-key",
        session_cache_enabled=session_cache_enabled,
        timeout_seconds=30.0,
        max_retries=0,
        max_input_chars=12000,
        extra_body={},
    )


def _request() -> LlmInvokeRequest:
    return LlmInvokeRequest(
        task_name="gmail_message_segment_plan",
        system_prompt="Return JSON.",
        user_payload={"message": {"subject": "hello"}},
        output_schema_name="AnyObject",
        output_schema_json={"type": "object"},
        source_id=1,
        request_id="req-1",
        source_provider="gmail",
    )


def test_responses_user_prompt_omits_dynamic_request_metadata() -> None:
    payload = build_responses_payload(
        invoke_request=_request(),
        profile=_profile(session_cache_enabled=True),
        truncated_input_json='{"message":{"subject":"hello"}}',
    )
    prompt = str(payload["input"])
    assert "REQUEST_ID" not in prompt
    assert "SOURCE_ID" not in prompt
    assert "SOURCE_PROVIDER" not in prompt
    assert "TASK: gmail_message_segment_plan" in prompt


def test_responses_user_prompt_places_message_context_in_shared_prefix() -> None:
    payload = build_responses_payload(
        invoke_request=LlmInvokeRequest(
            task_name="gmail_segment_atomic_extract",
            system_prompt="Return JSON.",
            user_payload={"stage": "atomic_extract", "segment": {"snippet": "HW moved"}},
            shared_user_payload={"message_id": "msg-1", "subject": "Subject", "body_text": "Body"},
            output_schema_name="AnyObject",
            output_schema_json={"type": "object"},
            source_id=1,
            request_id="req-1",
            source_provider="gmail",
        ),
        profile=_profile(session_cache_enabled=True),
        truncated_input_json='{"ignored":"because_shared_payload_is_used"}',
    )
    prompt = str(payload["input"])
    assert '"message_context"' in prompt
    assert '"task_input"' in prompt
    assert '"body_text":"Body"' in prompt
    assert 'TASK:' not in prompt


def test_responses_user_prompt_places_cache_prefix_before_task_input() -> None:
    payload = build_responses_payload(
        invoke_request=LlmInvokeRequest(
            task_name="gmail_purpose_mode_classify",
            system_prompt="Return JSON.",
            user_payload={"purpose": "assignment_or_exam_monitoring"},
            cache_prefix_payload={
                "policy_version": "gmail-cache-v1",
                "policy_text": "shared rules",
                "source_message": {"message_id": "msg-1", "body_text": "Body"},
            },
            output_schema_name="AnyObject",
            output_schema_json={"type": "object"},
            source_id=1,
            request_id="req-1",
            source_provider="gmail",
        ),
        profile=_profile(session_cache_enabled=True),
        truncated_input_json='{"purpose":"assignment_or_exam_monitoring"}',
    )
    prompt = str(payload["input"])
    assert '"cache_prefix"' in prompt
    assert '"task_input"' in prompt
    assert prompt.index('"cache_prefix"') < prompt.index('"task_input"')
    assert '"policy_text":"shared rules"' in prompt


def test_responses_payload_includes_previous_response_id_when_provided() -> None:
    payload = build_responses_payload(
        invoke_request=LlmInvokeRequest(
            task_name="gmail_atomic_semantic_extract",
            system_prompt="Return JSON.",
            user_payload={"mode": "atomic"},
            previous_response_id="resp-123",
            output_schema_name="AnyObject",
            output_schema_json={"type": "object"},
            source_id=1,
            request_id="req-1",
            source_provider="gmail",
        ),
        profile=_profile(session_cache_enabled=True),
        truncated_input_json='{"mode":"atomic"}',
    )
    assert payload["previous_response_id"] == "resp-123"


def test_transport_adds_session_cache_header_when_enabled(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        status_code = 200
        headers = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}], "usage": {}}

    class _FakeClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            captured["timeout"] = kwargs.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN201
            return False

        def post(self, endpoint, *, headers, json):  # noqa: ANN001
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setattr("app.modules.llm_gateway.transport_openai_compat.httpx.Client", _FakeClient)
    transport = OpenAICompatTransport()
    transport.post_json(
        profile=_profile(session_cache_enabled=True, vendor="dashscope_openai"),
        payload={"model": "test-model", "input": "hello"},
        request_context={"request_id": "req-1"},
    )
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers.get("x-dashscope-session-cache") == "enable"


def test_chat_completions_payload_places_cache_prefix_at_start() -> None:
    payload = build_chat_completions_payload(
        invoke_request=LlmInvokeRequest(
            task_name="gmail_atomic_semantic_extract",
            system_prompt="Extract semantic data.",
            user_payload={"purpose": "assignment_or_exam_monitoring"},
            cache_prefix_payload={
                "message_id": "msg-1",
                "subject": "Subject",
                "body_text": "Body text",
            },
            output_schema_name="AnyObject",
            output_schema_json={"type": "object"},
            source_id=1,
            request_id="req-1",
            source_provider="gmail",
            protocol_override="chat_completions",
            session_cache_mode="enable",
        ),
        profile=ResolvedLlmProfile(
            provider_id="env-default",
            vendor="openai",
            protocol="chat_completions",
            base_url="https://example.com/v1",
            model="test-model",
            api_key="test-key",
            session_cache_enabled=False,
            timeout_seconds=30.0,
            max_retries=0,
            max_input_chars=12000,
            extra_body={},
        ),
        truncated_input_json='{"purpose":"assignment_or_exam_monitoring"}',
    )
    messages = payload["messages"]
    assert isinstance(messages, list)
    assert messages[1]["role"] == "system"
    content = messages[1]["content"]
    assert isinstance(content, list)
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert "SOURCE_PREFIX_JSON:" in content[0]["text"]
    assert '"message_id":"msg-1"' in content[0]["text"]


def test_chat_completions_task_prompt_keeps_task_specific_tail_outside_cache_prefix() -> None:
    payload = build_chat_completions_payload(
        invoke_request=LlmInvokeRequest(
            task_name="gmail_purpose_mode_classify",
            system_prompt="Classify as unknown, atomic, or directive.",
            user_payload={"purpose": "assignment_or_exam_monitoring"},
            cache_prefix_payload={"message_id": "msg-1", "subject": "Subject"},
            output_schema_name="AnyObject",
            output_schema_json={"type": "object"},
            source_id=1,
            request_id="req-1",
            source_provider="gmail",
            protocol_override="chat_completions",
            session_cache_mode="enable",
        ),
        profile=ResolvedLlmProfile(
            provider_id="env-default",
            vendor="openai",
            protocol="chat_completions",
            base_url="https://example.com/v1",
            model="test-model",
            api_key="test-key",
            session_cache_enabled=False,
            timeout_seconds=30.0,
            max_retries=0,
            max_input_chars=12000,
            extra_body={},
        ),
        truncated_input_json='{"purpose":"assignment_or_exam_monitoring"}',
    )
    user_message = payload["messages"][2]
    assert user_message["role"] == "user"
    assert "TASK_INSTRUCTIONS:" in user_message["content"]
    assert "Classify as unknown, atomic, or directive." in user_message["content"]
    assert "TASK_INPUT_JSON:" in user_message["content"]


def test_chat_completions_can_cache_task_prompt_and_leave_message_body_in_tail() -> None:
    payload = build_chat_completions_payload(
        invoke_request=LlmInvokeRequest(
            task_name="gmail_purpose_mode_classify",
            system_prompt="Classify as unknown, atomic, or directive with few-shots.",
            user_payload={
                "purpose": "assignment_or_exam_monitoring",
                "message_context": {
                    "message_id": "msg-1",
                    "subject": "Homework 3 due tonight",
                    "body_text": "Homework 3 is now due tonight by 11:59 PM.",
                },
            },
            cache_prefix_payload={"cache_scope": "gmail_purpose_mode_classify:v2"},
            cache_task_prompt=True,
            output_schema_name="AnyObject",
            output_schema_json={"type": "object"},
            source_id=1,
            request_id="req-1",
            source_provider="gmail",
            protocol_override="chat_completions",
            session_cache_mode="enable",
        ),
        profile=ResolvedLlmProfile(
            provider_id="env-default",
            vendor="dashscope_openai",
            protocol="chat_completions",
            base_url="https://example.com/v1",
            model="test-model",
            api_key="test-key",
            session_cache_enabled=False,
            timeout_seconds=30.0,
            max_retries=0,
            max_input_chars=12000,
            extra_body={},
        ),
        truncated_input_json='{"purpose":"assignment_or_exam_monitoring","message_context":{"message_id":"msg-1","subject":"Homework 3 due tonight","body_text":"Homework 3 is now due tonight by 11:59 PM."}}',
    )
    cached_message = payload["messages"][1]
    user_message = payload["messages"][2]
    cached_content = cached_message["content"][0]["text"]
    assert "TASK_INSTRUCTIONS:" in cached_content
    assert "Classify as unknown, atomic, or directive with few-shots." in cached_content
    assert "Schema JSON:" in cached_content
    assert "CACHE_CONTEXT_JSON:" in cached_content
    assert '"cache_scope":"gmail_purpose_mode_classify:v2"' in cached_content
    assert "Homework 3 due tonight" not in cached_content
    assert user_message["role"] == "user"
    assert user_message["content"].startswith("TASK_INPUT_JSON:")
    assert "Homework 3 due tonight" in user_message["content"]
    assert "TASK_INSTRUCTIONS:" not in user_message["content"]
