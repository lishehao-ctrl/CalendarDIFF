from __future__ import annotations

from dataclasses import asdict, dataclass

from app.modules.llm_gateway.contracts import (
    LlmGatewayError,
    LlmInvokeRequest,
    LlmInvokeResult,
    LlmProtocolLiteral,
    LlmStreamRequest,
)
from app.modules.llm_gateway.route_registry import ResolvedLlmRoute
from app.modules.llm_gateway.usage_normalizer import normalize_llm_usage


@dataclass(frozen=True)
class LlmGatewayTraceEvent:
    request_id: str | None
    source_id: int | None
    task_name: str
    profile_family: str
    route_id: str
    route_index: int
    route_count: int
    is_fallback: bool
    provider_id: str
    vendor: str
    model: str
    protocol: LlmProtocolLiteral
    session_cache_enabled: bool
    success: bool
    latency_ms: int | None
    upstream_request_id: str | None
    response_id: str | None
    error_code: str | None
    retryable: bool | None
    http_status: int | None
    usage: dict[str, int | None] | None

    def as_payload(self) -> dict:
        return asdict(self)


def build_trace_event(
    *,
    invoke_request: LlmInvokeRequest | LlmStreamRequest,
    route: ResolvedLlmRoute,
    route_index: int,
    route_count: int,
    result: LlmInvokeResult | None = None,
    error: LlmGatewayError | None = None,
) -> LlmGatewayTraceEvent:
    usage = None
    if result is not None:
        usage = normalize_llm_usage(result.raw_usage if isinstance(result.raw_usage, dict) else None)
    return LlmGatewayTraceEvent(
        request_id=invoke_request.request_id,
        source_id=invoke_request.source_id,
        task_name=invoke_request.task_name,
        profile_family=invoke_request.profile_family,
        route_id=route.route_id,
        route_index=route_index,
        route_count=route_count,
        is_fallback=route.is_fallback,
        provider_id=route.profile.provider_id,
        vendor=route.profile.vendor,
        model=route.profile.model,
        protocol=route.profile.protocol,
        session_cache_enabled=route.profile.session_cache_enabled,
        success=result is not None,
        latency_ms=result.latency_ms if result is not None else None,
        upstream_request_id=result.upstream_request_id if result is not None else None,
        response_id=result.response_id if result is not None else None,
        error_code=error.code if error is not None else None,
        retryable=error.retryable if error is not None else None,
        http_status=error.http_status if error is not None else None,
        usage=usage,
    )


__all__ = [
    "LlmGatewayTraceEvent",
    "build_trace_event",
]
