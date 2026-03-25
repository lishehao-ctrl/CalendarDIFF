from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator, Mapping

import httpx

from app.modules.llm_gateway.adapters.gemini_generate_content import (
    extract_gemini_generate_content_json,
    extract_gemini_text,
)
from app.modules.llm_gateway.contracts import (
    LlmGatewayError,
    LlmProtocolLiteral,
    LlmStreamEvent,
    ResolvedLlmProfile,
)
from app.modules.llm_gateway.request_limiter import get_global_request_limiter

logger = logging.getLogger(__name__)


class GeminiNativeTransport:
    def post_json(
        self,
        *,
        profile: ResolvedLlmProfile,
        payload: dict,
        request_context: Mapping[str, object] | None = None,
    ) -> tuple[dict, int, str | None]:
        attempts = max(int(profile.max_retries), 0) + 1
        last_error: LlmGatewayError | None = None
        for attempt in range(1, attempts + 1):
            try:
                return self._post_json_once(profile=profile, payload=payload, request_context=request_context)
            except LlmGatewayError as exc:
                last_error = exc
                if not exc.retryable or attempt >= attempts:
                    break
        assert last_error is not None
        raise last_error

    def stream_events(
        self,
        *,
        profile: ResolvedLlmProfile,
        payload: dict,
        request_context: Mapping[str, object] | None = None,
    ) -> Iterator[LlmStreamEvent]:
        acquire_result = get_global_request_limiter().acquire()
        if acquire_result.waited_ms > 0:
            logger.info(
                "llm_transport.window_wait request_id=%s source_id=%s task_name=%s provider_id=%s model=%s "
                "waited_ms=%s in_window=%s window_seconds=%s max_requests=%s",
                _ctx(request_context, "request_id"),
                _ctx(request_context, "source_id"),
                _ctx(request_context, "task_name"),
                profile.provider_id,
                profile.model,
                acquire_result.waited_ms,
                acquire_result.in_window,
                acquire_result.window_seconds,
                acquire_result.max_requests,
            )
        endpoint = build_gemini_native_endpoint(base_url=profile.base_url, model=profile.model, stream=True)
        headers = {"x-goog-api-key": profile.api_key, "Content-Type": "application/json"}
        timeout = _build_timeout(profile=profile)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            started = time.perf_counter()
            try:
                with client.stream("POST", endpoint, headers=headers, json=_merge_extra_body(payload=payload, profile=profile)) as response:
                    response.raise_for_status()
                    upstream_request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
                    final_usage: dict = {}
                    response_id: str | None = None
                    for line in response.iter_lines():
                        text = (line or "").strip()
                        if not text:
                            continue
                        if text.startswith("data:"):
                            text = text[5:].strip()
                        if text == "[DONE]":
                            continue
                        chunk_json = json.loads(text)
                        if not isinstance(chunk_json, dict):
                            continue
                        response_id = _response_id_text(chunk_json) or response_id
                        usage = chunk_json.get("usageMetadata")
                        if isinstance(usage, dict):
                            final_usage = usage
                        delta = _extract_delta_text(chunk_json)
                        if delta:
                            yield LlmStreamEvent(
                                event_type="delta",
                                provider_id=profile.provider_id,
                                vendor=profile.vendor,
                                protocol=profile.protocol,
                                model=profile.model,
                                text_delta=delta,
                                response_id=response_id,
                                upstream_request_id=upstream_request_id,
                                raw_usage={},
                                vendor_event_type="gemini_candidate_chunk",
                            )
                    latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
                    yield LlmStreamEvent(
                        event_type="completed",
                        provider_id=profile.provider_id,
                        vendor=profile.vendor,
                        protocol=profile.protocol,
                        model=profile.model,
                        response_id=response_id,
                        upstream_request_id=upstream_request_id,
                        raw_usage=final_usage,
                        vendor_event_type="gemini_stream_completed",
                    )
                    logger.info(
                        "llm_transport.stream_ok request_id=%s source_id=%s task_name=%s provider_id=%s model=%s latency_ms=%s endpoint=%s",
                        _ctx(request_context, "request_id"),
                        _ctx(request_context, "source_id"),
                        _ctx(request_context, "task_name"),
                        profile.provider_id,
                        profile.model,
                        latency_ms,
                        endpoint,
                    )
            except httpx.TimeoutException as exc:
                raise _stream_error("parse_llm_timeout", str(exc), True, profile, 0) from exc
            except httpx.NetworkError as exc:
                raise _stream_error("parse_llm_upstream_error", f"llm network error: {exc}", True, profile, 0) from exc
            except httpx.HTTPStatusError as exc:
                retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
                raise _stream_error(
                    "parse_llm_upstream_error",
                    f"llm upstream http error: {exc.response.status_code}",
                    retryable,
                    profile,
                    exc.response.status_code,
                ) from exc

    def _post_json_once(
        self,
        *,
        profile: ResolvedLlmProfile,
        payload: dict,
        request_context: Mapping[str, object] | None,
    ) -> tuple[dict, int, str | None]:
        acquire_result = get_global_request_limiter().acquire()
        endpoint = build_gemini_native_endpoint(base_url=profile.base_url, model=profile.model, stream=False)
        headers = {"x-goog-api-key": profile.api_key, "Content-Type": "application/json"}
        timeout = _build_timeout(profile=profile)
        if acquire_result.waited_ms > 0:
            logger.info(
                "llm_transport.window_wait request_id=%s source_id=%s task_name=%s provider_id=%s model=%s "
                "waited_ms=%s in_window=%s window_seconds=%s max_requests=%s",
                _ctx(request_context, "request_id"),
                _ctx(request_context, "source_id"),
                _ctx(request_context, "task_name"),
                profile.provider_id,
                profile.model,
                acquire_result.waited_ms,
                acquire_result.in_window,
                acquire_result.window_seconds,
                acquire_result.max_requests,
            )
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.post(endpoint, headers=headers, json=_merge_extra_body(payload=payload, profile=profile))
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise _stream_error("parse_llm_timeout", f"llm request timeout: {exc}", True, profile, None) from exc
        except httpx.NetworkError as exc:
            raise _stream_error("parse_llm_upstream_error", f"llm network error: {exc}", True, profile, None) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            retryable = status_code == 429 or status_code >= 500
            raise _stream_error(
                "parse_llm_upstream_error",
                f"llm upstream http error: {status_code}",
                retryable,
                profile,
                status_code,
            ) from exc
        latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
        response_json = response.json()
        if not isinstance(response_json, dict):
            raise _stream_error("parse_llm_schema_invalid", "gemini response root must be object", False, profile, response.status_code)
        _payload, _usage, _response_id = extract_gemini_generate_content_json(
            response_json=response_json,
            provider_id=profile.provider_id,
            protocol=profile.protocol,
        )
        upstream_request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        return response_json, latency_ms, upstream_request_id


def build_gemini_native_endpoint(*, base_url: str, model: str, stream: bool) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ValueError("base_url is required")
    suffix = ":streamGenerateContent?alt=sse" if stream else ":generateContent"
    if "{model}" in normalized:
        return normalized.format(model=model) + suffix
    if normalized.endswith(":generateContent") or normalized.endswith(":streamGenerateContent"):
        return normalized if not stream else normalized.split("?", 1)[0] + "?alt=sse"
    return f"{normalized}/{model}{suffix}"


def _extract_delta_text(chunk_json: dict) -> str:
    candidates = chunk_json.get("candidates")
    if not isinstance(candidates, list):
        return ""
    chunks: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks)


def _response_id_text(payload: dict) -> str | None:
    raw = payload.get("responseId") or payload.get("response_id")
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def _build_timeout(*, profile: ResolvedLlmProfile) -> httpx.Timeout | None:
    if profile.timeout_seconds <= 0:
        return None
    return httpx.Timeout(
        connect=max(profile.timeout_seconds, 1.0),
        read=max(profile.timeout_seconds, 1.0),
        write=max(profile.timeout_seconds, 1.0),
        pool=max(profile.timeout_seconds, 1.0),
    )


def _merge_extra_body(*, payload: dict, profile: ResolvedLlmProfile) -> dict:
    if not profile.extra_body:
        return payload
    merged = dict(payload)
    merged.update(profile.extra_body)
    return merged


def _stream_error(
    code: str,
    message: str,
    retryable: bool,
    profile: ResolvedLlmProfile,
    http_status: int | None,
) -> LlmGatewayError:
    return LlmGatewayError(
        code=code,
        message=message,
        retryable=retryable,
        provider_id=profile.provider_id,
        protocol=profile.protocol,
        http_status=http_status,
    )


def _ctx(request_context: Mapping[str, object] | None, key: str) -> str:
    if request_context is None:
        return "-"
    value = request_context.get(key)
    if value is None:
        return "-"
    return str(value)


__all__ = ["GeminiNativeTransport", "build_gemini_native_endpoint"]
