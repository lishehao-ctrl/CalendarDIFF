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
    del invoke_request
    del primary_protocol
    settings = get_settings()
    return LlmRoutePolicy(
        allow_fallback=False,
        fallback_protocols=(),
        max_routes=1,
        persist_traces=bool(settings.llm_gateway_trace_persistence_enabled),
    )


__all__ = [
    "LlmRoutePolicy",
    "resolve_route_policy",
]
