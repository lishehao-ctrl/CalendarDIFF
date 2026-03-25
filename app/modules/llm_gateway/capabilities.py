from __future__ import annotations

from dataclasses import dataclass

from app.modules.llm_gateway.contracts import (
    LlmInvokeRequest,
    LlmProtocolLiteral,
    ResolvedLlmProfile,
)


_CAPABILITY_MATRIX: dict[tuple[str, str], tuple[bool, bool, bool, bool, bool]] = {
    ("openai", "responses"): (True, True, False, False, False),
    ("openai", "chat_completions"): (False, False, True, False, True),
    ("dashscope_openai", "responses"): (True, True, False, True, False),
    ("dashscope_openai", "chat_completions"): (False, False, True, False, True),
    ("gemini", "gemini_generate_content"): (True, False, False, False, True),
    ("gemini", "chat_completions"): (False, False, False, False, True),
}


@dataclass(frozen=True)
class LlmProviderCapabilities:
    native_structured_json_supported: bool
    previous_response_supported: bool
    prompt_cache_block_supported: bool
    session_cache_header_supported: bool
    streaming_supported: bool


def capabilities_for_profile(*, profile: ResolvedLlmProfile) -> LlmProviderCapabilities:
    matrix_entry = _CAPABILITY_MATRIX.get((profile.vendor, profile.protocol))
    if matrix_entry is None:
        matrix_entry = (False, False, False, False, False)
    return LlmProviderCapabilities(
        native_structured_json_supported=matrix_entry[0],
        previous_response_supported=matrix_entry[1],
        prompt_cache_block_supported=matrix_entry[2],
        session_cache_header_supported=matrix_entry[3],
        streaming_supported=matrix_entry[4],
    )


def adapt_request_for_capabilities(
    *,
    invoke_request: LlmInvokeRequest,
    capabilities: LlmProviderCapabilities,
) -> LlmInvokeRequest:
    if capabilities.previous_response_supported or invoke_request.previous_response_id is None:
        return invoke_request
    return LlmInvokeRequest(
        task_name=invoke_request.task_name,
        system_prompt=invoke_request.system_prompt,
        user_payload=invoke_request.user_payload,
        output_schema_name=invoke_request.output_schema_name,
        output_schema_json=invoke_request.output_schema_json,
        profile_family=invoke_request.profile_family,
        source_id=invoke_request.source_id,
        request_id=invoke_request.request_id,
        source_provider=invoke_request.source_provider,
        temperature=invoke_request.temperature,
        shared_user_payload=invoke_request.shared_user_payload,
        cache_prefix_payload=invoke_request.cache_prefix_payload,
        cache_task_prompt=invoke_request.cache_task_prompt,
        previous_response_id=None,
        protocol_override=invoke_request.protocol_override,
        session_cache_mode=invoke_request.session_cache_mode,
    )


def fallback_protocols_for_profile(*, profile: ResolvedLlmProfile) -> tuple[LlmProtocolLiteral, ...]:
    if profile.vendor not in {"openai", "dashscope_openai"}:
        return ()
    if profile.protocol == "responses":
        return ("chat_completions",)
    if profile.protocol == "chat_completions":
        return ("responses",)
    return ()


__all__ = [
    "LlmProviderCapabilities",
    "adapt_request_for_capabilities",
    "capabilities_for_profile",
    "fallback_protocols_for_profile",
]
