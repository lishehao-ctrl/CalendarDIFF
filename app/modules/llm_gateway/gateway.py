from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import replace

from sqlalchemy.orm import Session

from app.modules.llm_gateway.adapters.chat_completions import (
    build_chat_completions_payload,
    build_chat_completions_stream_payload,
    extract_chat_completions_json,
)
from app.modules.llm_gateway.adapters.gemini_generate_content import (
    build_gemini_generate_content_payload,
    build_gemini_stream_payload,
    extract_gemini_generate_content_json,
)
from app.modules.llm_gateway.adapters.responses import (
    build_responses_payload,
    extract_responses_json,
)
from app.modules.llm_gateway.capabilities import adapt_request_for_capabilities, capabilities_for_profile
from app.modules.llm_gateway.contracts import (
    LlmGatewayError,
    LlmInvokeRequest,
    LlmInvokeResult,
    LlmProtocolLiteral,
    LlmStreamEvent,
    LlmStreamRequest,
    ResolvedLlmProfile,
)
from app.modules.llm_gateway.invocation_log import record_llm_invocation_trace
from app.modules.llm_gateway.json_contract import truncate_user_payload, validate_schema
from app.modules.llm_gateway.registry import resolve_llm_base_url
from app.modules.llm_gateway.route_policy import resolve_route_policy
from app.modules.llm_gateway.route_registry import ResolvedLlmRoute, resolve_llm_routes
from app.modules.llm_gateway.runtime_control import (
    get_llm_invoke_observer,
    get_llm_trace_observer,
    get_session_cache_mode_override,
)
from app.modules.llm_gateway.timeout_policy import with_dynamic_timeout
from app.modules.llm_gateway.tracing import LlmGatewayTraceEvent, build_trace_event
from app.modules.llm_gateway.transport_gemini_native import GeminiNativeTransport
from app.modules.llm_gateway.transport_openai_compat import OpenAICompatTransport
from app.modules.llm_gateway.retry_policy import LLM_FORMAT_MAX_ATTEMPTS, is_format_retryable_code
from app.modules.llm_gateway.usage_normalizer import normalize_llm_usage
from app.modules.llm_gateway.usage_tracking import record_sync_request_llm_usage

logger = logging.getLogger(__name__)


class LlmGateway:
    def __init__(
        self,
        *,
        transport: OpenAICompatTransport | None = None,
        openai_transport: OpenAICompatTransport | None = None,
        gemini_transport: GeminiNativeTransport | None = None,
    ) -> None:
        self._openai_transport = openai_transport or transport or OpenAICompatTransport()
        self._gemini_transport = gemini_transport or GeminiNativeTransport()

    def invoke_json(self, db: Session, *, invoke_request: LlmInvokeRequest) -> LlmInvokeResult:
        try:
            routes = resolve_llm_routes(db, invoke_request=invoke_request)
        except LlmGatewayError as exc:
            self._log_top_level_error(invoke_request=invoke_request, error=exc)
            raise

        route_count = len(routes)
        last_error: LlmGatewayError | None = None
        for route_index, route in enumerate(routes, start=1):
            try:
                result = self._invoke_via_route(
                    route=route,
                    invoke_request=invoke_request,
                    route_index=route_index,
                    route_count=route_count,
                )
                return result
            except LlmGatewayError as exc:
                last_error = exc
                self._emit_trace(
                    invoke_request=invoke_request,
                    route=route,
                    route_index=route_index,
                    route_count=route_count,
                    error=exc,
                )
                if not exc.retryable or route_index >= route_count:
                    raise
                logger.warning(
                    "llm_gateway.invoke_json route_fallback request_id=%s source_id=%s task_name=%s from_route=%s to_route=%s error_code=%s",
                    invoke_request.request_id or "-",
                    invoke_request.source_id if invoke_request.source_id is not None else "-",
                    invoke_request.task_name,
                    route.route_id,
                    routes[route_index].route_id,
                    exc.code,
                )
        assert last_error is not None
        raise last_error

    def invoke_stream(self, db: Session, *, stream_request: LlmStreamRequest) -> Iterator[LlmStreamEvent]:
        routes = resolve_llm_routes(db, invoke_request=stream_request)
        route_count = len(routes)

        def _generator() -> Iterator[LlmStreamEvent]:
            for route_index, route in enumerate(routes, start=1):
                yielded_any = False
                try:
                    for event in self._stream_via_route(
                        route=route,
                        stream_request=stream_request,
                        route_index=route_index,
                        route_count=route_count,
                    ):
                        yielded_any = True
                        yield event
                    return
                except LlmGatewayError as exc:
                    self._emit_trace(
                        invoke_request=stream_request,
                        route=route,
                        route_index=route_index,
                        route_count=route_count,
                        error=exc,
                    )
                    if yielded_any:
                        yield self._build_stream_error_event(route=route, message=str(exc), error_code=exc.code)
                        return
                    if exc.retryable and route_index < route_count:
                        continue
                    yield self._build_stream_error_event(route=route, message=str(exc), error_code=exc.code)
                    return

        return _generator()

    def _invoke_via_route(
        self,
        *,
        route: ResolvedLlmRoute,
        invoke_request: LlmInvokeRequest,
        route_index: int,
        route_count: int,
    ) -> LlmInvokeResult:
        provider_id = route.profile.provider_id
        model = route.profile.model
        for attempt in range(1, LLM_FORMAT_MAX_ATTEMPTS + 1):
            try:
                result = self._invoke_json_once(
                    profile=route.profile,
                    route_id=route.route_id,
                    invoke_request=invoke_request,
                )
                logger.info(
                    "llm_gateway.invoke_json ok request_id=%s source_id=%s task_name=%s provider_id=%s model=%s "
                    "latency_ms=%s error_code=- retryable=- http_status=- attempt=%s/%s route=%s route_attempt=%s/%s",
                    invoke_request.request_id or "-",
                    invoke_request.source_id if invoke_request.source_id is not None else "-",
                    invoke_request.task_name,
                    result.provider_id,
                    result.model,
                    result.latency_ms,
                    attempt,
                    LLM_FORMAT_MAX_ATTEMPTS,
                    route.route_id,
                    route_index,
                    route_count,
                )
                self._emit_trace(
                    invoke_request=invoke_request,
                    route=route,
                    route_index=route_index,
                    route_count=route_count,
                    result=result,
                )
                return result
            except LlmGatewayError as exc:
                if is_format_retryable_code(exc.code) and attempt < LLM_FORMAT_MAX_ATTEMPTS:
                    logger.warning(
                        "llm_gateway.invoke_json format_retry request_id=%s source_id=%s task_name=%s provider_id=%s model=%s error_code=%s attempt=%s/%s route=%s",
                        invoke_request.request_id or "-",
                        invoke_request.source_id if invoke_request.source_id is not None else "-",
                        invoke_request.task_name,
                        exc.provider_id or provider_id,
                        model,
                        exc.code,
                        attempt,
                        LLM_FORMAT_MAX_ATTEMPTS,
                        route.route_id,
                    )
                    continue
                raise

    def _stream_via_route(
        self,
        *,
        route: ResolvedLlmRoute,
        stream_request: LlmStreamRequest,
        route_index: int,
        route_count: int,
    ) -> Iterator[LlmStreamEvent]:
        capabilities = capabilities_for_profile(profile=route.profile)
        if not capabilities.streaming_supported:
            raise LlmGatewayError(
                code="parse_llm_stream_unsupported",
                message=f"streaming is not supported for protocol '{route.profile.protocol}'",
                retryable=False,
                provider_id=route.profile.provider_id,
                protocol=route.profile.protocol,
            )
        effective_profile = self._apply_session_cache_override(route.profile, stream_request.session_cache_mode)
        payload = _build_stream_payload(
            stream_request=stream_request,
            profile=effective_profile,
        )
        request_context = {
            "request_id": stream_request.request_id or "-",
            "source_id": stream_request.source_id if stream_request.source_id is not None else "-",
            "task_name": stream_request.task_name,
            "model": effective_profile.model,
            "provider_id": effective_profile.provider_id,
            "route_id": route.route_id,
        }
        transport = self._transport_for_profile(effective_profile)
        started = time.perf_counter()
        final_usage: dict = {}
        response_id: str | None = None
        upstream_request_id: str | None = None
        for event in transport.stream_events(
            profile=effective_profile,
            payload=payload,
            request_context=request_context,
        ):
            if event.response_id:
                response_id = event.response_id
            if event.upstream_request_id:
                upstream_request_id = event.upstream_request_id
            if isinstance(event.raw_usage, dict) and event.raw_usage:
                final_usage = event.raw_usage
            yield event
            if event.event_type == "completed":
                latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
                self._emit_stream_completion(
                    route=route,
                    stream_request=stream_request,
                    route_index=route_index,
                    route_count=route_count,
                    latency_ms=latency_ms,
                    response_id=response_id,
                    upstream_request_id=upstream_request_id,
                    raw_usage=final_usage,
                )

    def _invoke_json_once(
        self,
        *,
        profile: ResolvedLlmProfile,
        route_id: str | None,
        invoke_request: LlmInvokeRequest,
    ) -> LlmInvokeResult:
        capabilities = capabilities_for_profile(profile=profile)
        effective_request = adapt_request_for_capabilities(
            invoke_request=invoke_request,
            capabilities=capabilities,
        )
        truncated_input_json = truncate_user_payload(
            user_payload=effective_request.user_payload,
            profile=profile,
        )
        effective_profile = with_dynamic_timeout(
            profile=profile,
            invoke_request=effective_request,
            truncated_input_json=truncated_input_json,
        )
        if effective_request.protocol_override is not None:
            effective_profile = replace(
                effective_profile,
                protocol=effective_request.protocol_override,
                base_url=resolve_llm_base_url(
                    protocol=effective_request.protocol_override,
                    fallback_base_url=effective_profile.base_url,
                    provider_id=effective_profile.provider_id,
                ),
            )
        effective_profile = self._apply_session_cache_override(effective_profile, effective_request.session_cache_mode)
        request_payload = _build_request_payload(
            invoke_request=effective_request,
            profile=effective_profile,
            truncated_input_json=truncated_input_json,
        )
        transport = self._transport_for_profile(effective_profile)
        response_json, latency_ms, upstream_request_id = transport.post_json(
            profile=effective_profile,
            payload=request_payload,
            request_context={
                "request_id": invoke_request.request_id or "-",
                "source_id": invoke_request.source_id if invoke_request.source_id is not None else "-",
                "task_name": invoke_request.task_name,
                "model": effective_profile.model,
                "provider_id": effective_profile.provider_id,
                "route_id": route_id or "-",
            },
        )
        extracted_json, raw_usage, response_id = _extract_result(
            response_json=response_json,
            provider_id=effective_profile.provider_id,
            protocol=effective_profile.protocol,
        )
        validate_schema(
            payload=extracted_json,
            schema=invoke_request.output_schema_json,
            schema_name=invoke_request.output_schema_name,
            provider_id=effective_profile.provider_id,
            protocol=effective_profile.protocol,
        )
        result = LlmInvokeResult(
            json_object=extracted_json,
            provider_id=effective_profile.provider_id,
            protocol=effective_profile.protocol,
            model=effective_profile.model,
            latency_ms=latency_ms,
            response_id=response_id,
            upstream_request_id=upstream_request_id,
            raw_usage=raw_usage,
            route_id=route_id,
            vendor=effective_profile.vendor,
        )
        observer = get_llm_invoke_observer()
        if observer is not None:
            observer(invoke_request, result)
        record_sync_request_llm_usage(invoke_request=invoke_request, result=result)
        return result

    def _transport_for_profile(self, profile: ResolvedLlmProfile):
        if profile.vendor == "gemini" and profile.protocol == "gemini_generate_content":
            return self._gemini_transport
        return self._openai_transport

    def _apply_session_cache_override(
        self,
        profile: ResolvedLlmProfile,
        session_cache_mode: str,
    ) -> ResolvedLlmProfile:
        session_cache_mode_override = get_session_cache_mode_override()
        if session_cache_mode_override in {"enable", "disable"}:
            return replace(profile, session_cache_enabled=(session_cache_mode_override == "enable"))
        if session_cache_mode in {"enable", "disable"}:
            return replace(profile, session_cache_enabled=(session_cache_mode == "enable"))
        return profile

    def _emit_trace(
        self,
        *,
        invoke_request: LlmInvokeRequest | LlmStreamRequest,
        route: ResolvedLlmRoute,
        route_index: int,
        route_count: int,
        result: LlmInvokeResult | None = None,
        error: LlmGatewayError | None = None,
    ) -> None:
        trace_observer = get_llm_trace_observer()
        event = build_trace_event(
            invoke_request=invoke_request,
            route=route,
            route_index=route_index,
            route_count=route_count,
            result=result,
            error=error,
        )
        policy = resolve_route_policy(
            invoke_request=invoke_request,
            primary_protocol=route.profile.protocol,
        )
        if policy.persist_traces:
            record_llm_invocation_trace(event=event)
        if trace_observer is not None:
            trace_observer(event)

    def _emit_stream_completion(
        self,
        *,
        route: ResolvedLlmRoute,
        stream_request: LlmStreamRequest,
        route_index: int,
        route_count: int,
        latency_ms: int,
        response_id: str | None,
        upstream_request_id: str | None,
        raw_usage: dict,
    ) -> None:
        synthetic_result = LlmInvokeResult(
            json_object={},
            provider_id=route.profile.provider_id,
            protocol=route.profile.protocol,
            model=route.profile.model,
            latency_ms=latency_ms,
            response_id=response_id,
            upstream_request_id=upstream_request_id,
            raw_usage=raw_usage,
            route_id=route.route_id,
            vendor=route.profile.vendor,
        )
        synthetic_request = LlmInvokeRequest(
            task_name=stream_request.task_name,
            system_prompt=stream_request.system_prompt,
            user_payload=stream_request.user_payload,
            output_schema_name="StreamText",
            output_schema_json={"type": "string"},
            profile_family=stream_request.profile_family,
            source_id=stream_request.source_id,
            request_id=stream_request.request_id,
            source_provider=stream_request.source_provider,
            temperature=stream_request.temperature,
            shared_user_payload=stream_request.shared_user_payload,
            cache_prefix_payload=stream_request.cache_prefix_payload,
            previous_response_id=stream_request.previous_response_id,
            protocol_override=stream_request.protocol_override,
            session_cache_mode=stream_request.session_cache_mode,
        )
        observer = get_llm_invoke_observer()
        if observer is not None:
            observer(synthetic_request, synthetic_result)
        record_sync_request_llm_usage(invoke_request=synthetic_request, result=synthetic_result)
        trace_event = LlmGatewayTraceEvent(
            request_id=stream_request.request_id,
            source_id=stream_request.source_id,
            task_name=stream_request.task_name,
            profile_family=stream_request.profile_family,
            route_id=route.route_id,
            route_index=route_index,
            route_count=route_count,
            is_fallback=route.is_fallback,
            provider_id=route.profile.provider_id,
            vendor=route.profile.vendor,
            model=route.profile.model,
            protocol=route.profile.protocol,
            session_cache_enabled=route.profile.session_cache_enabled,
            success=True,
            latency_ms=latency_ms,
            upstream_request_id=upstream_request_id,
            response_id=response_id,
            error_code=None,
            retryable=None,
            http_status=None,
            usage=normalize_llm_usage(raw_usage if isinstance(raw_usage, dict) else None),
        )
        policy = resolve_route_policy(
            invoke_request=stream_request,
            primary_protocol=route.profile.protocol,
        )
        if policy.persist_traces:
            record_llm_invocation_trace(event=trace_event)
        trace_observer = get_llm_trace_observer()
        if trace_observer is not None:
            trace_observer(trace_event)

    def _build_stream_error_event(
        self,
        *,
        route: ResolvedLlmRoute,
        message: str,
        error_code: str,
    ) -> LlmStreamEvent:
        return LlmStreamEvent(
            event_type="error",
            provider_id=route.profile.provider_id,
            vendor=route.profile.vendor,
            protocol=route.profile.protocol,
            model=route.profile.model,
            text_delta=None,
            response_id=None,
            upstream_request_id=None,
            raw_usage={},
            vendor_event_type="gateway_error",
            error_code=error_code,
            error_message=message,
        )

    def _log_top_level_error(self, *, invoke_request: LlmInvokeRequest, error: LlmGatewayError) -> None:
        logger.warning(
            "llm_gateway.invoke_json failed request_id=%s source_id=%s task_name=%s provider_id=%s model=%s latency_ms=- error_code=%s retryable=%s http_status=%s",
            invoke_request.request_id or "-",
            invoke_request.source_id if invoke_request.source_id is not None else "-",
            invoke_request.task_name,
            error.provider_id or "-",
            "-",
            error.code,
            error.retryable,
            error.http_status if error.http_status is not None else "-",
        )


_GLOBAL_GATEWAY = LlmGateway()


def invoke_llm_json(db: Session, *, invoke_request: LlmInvokeRequest) -> LlmInvokeResult:
    return _GLOBAL_GATEWAY.invoke_json(db, invoke_request=invoke_request)


def invoke_llm_stream(db: Session, *, stream_request: LlmStreamRequest) -> Iterator[LlmStreamEvent]:
    return _GLOBAL_GATEWAY.invoke_stream(db, stream_request=stream_request)


def _build_request_payload(
    *,
    invoke_request: LlmInvokeRequest,
    profile: ResolvedLlmProfile,
    truncated_input_json: str,
) -> dict:
    if profile.protocol == "responses":
        return build_responses_payload(
            invoke_request=invoke_request,
            profile=profile,
            truncated_input_json=truncated_input_json,
        )
    if profile.protocol == "chat_completions":
        return build_chat_completions_payload(
            invoke_request=invoke_request,
            profile=profile,
            truncated_input_json=truncated_input_json,
        )
    return build_gemini_generate_content_payload(
        invoke_request=invoke_request,
        profile=profile,
        truncated_input_json=truncated_input_json,
    )


def _build_stream_payload(
    *,
    stream_request: LlmStreamRequest,
    profile: ResolvedLlmProfile,
) -> dict:
    if profile.protocol == "chat_completions":
        return build_chat_completions_stream_payload(
            stream_request=stream_request,
            profile=profile,
        )
    if profile.protocol == "gemini_generate_content":
        return build_gemini_stream_payload(
            stream_request=stream_request,
            profile=profile,
        )
    raise LlmGatewayError(
        code="parse_llm_stream_unsupported",
        message=f"streaming is not supported for protocol '{profile.protocol}'",
        retryable=False,
        provider_id=profile.provider_id,
        protocol=profile.protocol,
    )


def _extract_result(
    *,
    response_json: dict,
    provider_id: str,
    protocol: LlmProtocolLiteral,
) -> tuple[dict, dict, str | None]:
    if protocol == "responses":
        return extract_responses_json(
            response_json=response_json,
            provider_id=provider_id,
            protocol=protocol,
        )
    if protocol == "chat_completions":
        return extract_chat_completions_json(
            response_json=response_json,
            provider_id=provider_id,
            protocol=protocol,
        )
    return extract_gemini_generate_content_json(
        response_json=response_json,
        provider_id=provider_id,
        protocol=protocol,
    )


__all__ = [
    "LlmGateway",
    "invoke_llm_json",
    "invoke_llm_stream",
]
