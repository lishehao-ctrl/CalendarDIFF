from __future__ import annotations

from app.modules.llm_gateway.contracts import LlmInvokeRequest, ResolvedLlmProfile
from app.modules.llm_gateway.timeout_policy import estimate_input_tokens, with_dynamic_timeout


def _profile(*, timeout_seconds: float = 30.0) -> ResolvedLlmProfile:
    return ResolvedLlmProfile(
        provider_id="env-default",
        vendor="openai-compatible",
        base_url="https://example.com/v1",
        api_mode="responses",
        model="test-model",
        api_key="test-key",
        timeout_seconds=timeout_seconds,
        max_retries=1,
        max_input_chars=12000,
        extra_body={},
    )


def _invoke_request(task_name: str) -> LlmInvokeRequest:
    return LlmInvokeRequest(
        task_name=task_name,
        system_prompt="Return JSON object only.",
        user_payload={"message": {"subject": "hello"}},
        output_schema_name="AnyObject",
        output_schema_json={"type": "object"},
        source_id=1,
        request_id="req-1",
        source_provider="gmail",
    )


def test_estimate_input_tokens_uses_json_length_heuristic() -> None:
    assert estimate_input_tokens("") == 1
    assert estimate_input_tokens("abcd") == 1
    assert estimate_input_tokens("abcdefgh") == 2


def test_calendar_extract_timeout_gets_task_floor_and_token_padding() -> None:
    profile = with_dynamic_timeout(
        profile=_profile(timeout_seconds=30.0),
        invoke_request=_invoke_request("calendar_event_semantic_extract"),
        truncated_input_json="x" * 400,
    )

    assert profile.timeout_seconds > 90.0
    assert profile.timeout_seconds <= 180.0


def test_gmail_planner_timeout_respects_lower_task_floor() -> None:
    profile = with_dynamic_timeout(
        profile=_profile(timeout_seconds=30.0),
        invoke_request=_invoke_request("gmail_message_segment_plan"),
        truncated_input_json="x" * 80,
    )

    assert profile.timeout_seconds > 30.0
    assert profile.timeout_seconds < 40.0


def test_unknown_task_uses_base_timeout_plus_small_padding() -> None:
    profile = with_dynamic_timeout(
        profile=_profile(timeout_seconds=18.0),
        invoke_request=_invoke_request("unknown_task"),
        truncated_input_json="x" * 40,
    )

    assert profile.timeout_seconds > 18.0
    assert profile.timeout_seconds < 25.0
