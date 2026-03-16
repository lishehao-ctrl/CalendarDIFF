from __future__ import annotations

from dataclasses import replace

from app.modules.llm_gateway.contracts import LlmInvokeRequest, ResolvedLlmProfile

DEFAULT_TIMEOUT_CAP_SECONDS = 180.0

_TASK_MIN_TIMEOUT_SECONDS = {
    "calendar_event_semantic_extract": 90.0,
    "calendar_source_context_prime": 35.0,
    "calendar_purpose_relevance": 30.0,
    "calendar_semantic_extract": 90.0,
    "gmail_message_segment_plan": 25.0,
    "gmail_source_context_prime": 30.0,
    "gmail_purpose_mode_classify": 25.0,
    "gmail_segment_atomic_extract": 35.0,
    "gmail_segment_directive_extract": 40.0,
    "gmail_atomic_semantic_extract": 35.0,
    "gmail_directive_semantic_extract": 40.0,
    "course_raw_type_match": 20.0,
}


def with_dynamic_timeout(
    *,
    profile: ResolvedLlmProfile,
    invoke_request: LlmInvokeRequest,
    truncated_input_json: str,
) -> ResolvedLlmProfile:
    if profile.timeout_seconds <= 0:
        return profile
    estimated_input_tokens = estimate_input_tokens(truncated_input_json)
    effective_timeout_seconds = _resolve_timeout_seconds(
        base_timeout_seconds=profile.timeout_seconds,
        task_name=invoke_request.task_name,
        estimated_input_tokens=estimated_input_tokens,
    )
    if effective_timeout_seconds == profile.timeout_seconds:
        return profile
    return replace(profile, timeout_seconds=effective_timeout_seconds)


def estimate_input_tokens(truncated_input_json: str) -> int:
    cleaned = truncated_input_json.strip()
    if not cleaned:
        return 1
    # Coarse token estimate for mixed JSON/text payloads without model-specific tokenization.
    return max(1, (len(cleaned) + 3) // 4)


def _resolve_timeout_seconds(
    *,
    base_timeout_seconds: float,
    task_name: str,
    estimated_input_tokens: int,
) -> float:
    task_floor = _TASK_MIN_TIMEOUT_SECONDS.get(task_name, max(float(base_timeout_seconds), 1.0))
    base = max(float(base_timeout_seconds), task_floor)
    token_padding_seconds = min(60.0, estimated_input_tokens * 0.03)
    effective = min(DEFAULT_TIMEOUT_CAP_SECONDS, base + token_padding_seconds)
    return round(effective, 3)


__all__ = [
    "estimate_input_tokens",
    "with_dynamic_timeout",
]
