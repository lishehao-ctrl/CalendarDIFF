from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.modules.llm_gateway.contracts import LlmProtocolLiteral, LlmInvokeRequest, LlmStreamRequest


@dataclass(frozen=True)
class LlmRoutePolicy:
    allow_fallback: bool
    fallback_protocols: tuple[LlmProtocolLiteral, ...]
    max_routes: int
    persist_traces: bool


def resolve_route_policy(
    *,
    invoke_request: LlmInvokeRequest | LlmStreamRequest,
    primary_protocol: LlmProtocolLiteral,
) -> LlmRoutePolicy:
    settings = get_settings()
    no_fallback_tasks = {
        value.strip()
        for value in str(settings.llm_gateway_no_fallback_tasks or "").split(",")
        if value.strip()
    }
    family_fallback_enabled = (
        bool(settings.agent_llm_fallback_enabled)
        if invoke_request.profile_family == "agent"
        else bool(settings.ingestion_llm_fallback_enabled)
    )
    allow_fallback = (
        invoke_request.protocol_override is None
        and family_fallback_enabled
        and invoke_request.task_name not in no_fallback_tasks
    )
    ordered_modes: tuple[LlmProtocolLiteral, ...]
    if primary_protocol == "responses":
        ordered_modes = ("chat_completions",)
    elif primary_protocol == "chat_completions":
        ordered_modes = ("responses",)
    else:
        ordered_modes = ()
    return LlmRoutePolicy(
        allow_fallback=allow_fallback,
        fallback_protocols=ordered_modes,
        max_routes=max(int(settings.llm_gateway_max_routes_per_invoke), 1),
        persist_traces=bool(settings.llm_gateway_trace_persistence_enabled),
    )


__all__ = [
    "LlmRoutePolicy",
    "resolve_route_policy",
]
