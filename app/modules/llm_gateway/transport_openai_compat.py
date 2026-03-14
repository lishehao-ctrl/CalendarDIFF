from __future__ import annotations

import logging
import time
from collections.abc import Mapping

import httpx

from app.modules.llm_gateway.contracts import LlmApiModeLiteral, LlmGatewayError, ResolvedLlmProfile

logger = logging.getLogger(__name__)


class OpenAICompatTransport:
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
                if not exc.retryable:
                    break
                if attempt < attempts:
                    logger.info(
                        "llm_transport.retry request_id=%s source_id=%s task_name=%s provider_id=%s model=%s "
                        "attempt=%s/%s error_code=%s retryable=%s",
                        _ctx(request_context, "request_id"),
                        _ctx(request_context, "source_id"),
                        _ctx(request_context, "task_name"),
                        profile.provider_id,
                        profile.model,
                        attempt,
                        attempts,
                        exc.code,
                        exc.retryable,
                    )
        assert last_error is not None
        raise last_error

    def _post_json_once(
        self,
        *,
        profile: ResolvedLlmProfile,
        payload: dict,
        request_context: Mapping[str, object] | None,
    ) -> tuple[dict, int, str | None]:
        endpoint = build_openai_compat_endpoint(base_url=profile.base_url, api_mode=profile.api_mode)
        headers = {
            "Authorization": f"Bearer {profile.api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(
            connect=max(profile.timeout_seconds, 1.0),
            read=max(profile.timeout_seconds, 1.0),
            write=max(profile.timeout_seconds, 1.0),
            pool=max(profile.timeout_seconds, 1.0),
        )
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.post(endpoint, headers=headers, json=_merge_extra_body(payload=payload, profile=profile))
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.warning(
                "llm_transport.timeout request_id=%s source_id=%s task_name=%s provider_id=%s model=%s "
                "latency_ms=- error_code=parse_llm_timeout retryable=true http_status=- endpoint=%s",
                _ctx(request_context, "request_id"),
                _ctx(request_context, "source_id"),
                _ctx(request_context, "task_name"),
                profile.provider_id,
                profile.model,
                endpoint,
            )
            raise LlmGatewayError(
                code="parse_llm_timeout",
                message=f"llm request timeout: {exc}",
                retryable=True,
                provider_id=profile.provider_id,
                api_mode=profile.api_mode,
            ) from exc
        except httpx.NetworkError as exc:
            logger.warning(
                "llm_transport.network_error request_id=%s source_id=%s task_name=%s provider_id=%s model=%s "
                "latency_ms=- error_code=parse_llm_upstream_error retryable=true http_status=- endpoint=%s",
                _ctx(request_context, "request_id"),
                _ctx(request_context, "source_id"),
                _ctx(request_context, "task_name"),
                profile.provider_id,
                profile.model,
                endpoint,
            )
            raise LlmGatewayError(
                code="parse_llm_upstream_error",
                message=f"llm network error: {exc}",
                retryable=True,
                provider_id=profile.provider_id,
                api_mode=profile.api_mode,
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            retryable = status_code == 429 or status_code >= 500
            logger.warning(
                "llm_transport.http_error request_id=%s source_id=%s task_name=%s provider_id=%s model=%s "
                "latency_ms=- error_code=parse_llm_upstream_error retryable=%s http_status=%s endpoint=%s",
                _ctx(request_context, "request_id"),
                _ctx(request_context, "source_id"),
                _ctx(request_context, "task_name"),
                profile.provider_id,
                profile.model,
                retryable,
                status_code,
                endpoint,
            )
            raise LlmGatewayError(
                code="parse_llm_upstream_error",
                message=f"llm upstream http error: {status_code}",
                retryable=retryable,
                provider_id=profile.provider_id,
                api_mode=profile.api_mode,
                http_status=status_code,
            ) from exc
        latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
        try:
            response_json = response.json()
        except Exception as exc:
            logger.warning(
                "llm_transport.invalid_json request_id=%s source_id=%s task_name=%s provider_id=%s model=%s "
                "latency_ms=%s error_code=parse_llm_schema_invalid retryable=false http_status=%s endpoint=%s",
                _ctx(request_context, "request_id"),
                _ctx(request_context, "source_id"),
                _ctx(request_context, "task_name"),
                profile.provider_id,
                profile.model,
                latency_ms,
                response.status_code,
                endpoint,
            )
            raise LlmGatewayError(
                code="parse_llm_schema_invalid",
                message="llm response is not valid json",
                retryable=False,
                provider_id=profile.provider_id,
                api_mode=profile.api_mode,
                http_status=response.status_code,
            ) from exc
        if not isinstance(response_json, dict):
            logger.warning(
                "llm_transport.non_object_json request_id=%s source_id=%s task_name=%s provider_id=%s model=%s "
                "latency_ms=%s error_code=parse_llm_schema_invalid retryable=false http_status=%s endpoint=%s",
                _ctx(request_context, "request_id"),
                _ctx(request_context, "source_id"),
                _ctx(request_context, "task_name"),
                profile.provider_id,
                profile.model,
                latency_ms,
                response.status_code,
                endpoint,
            )
            raise LlmGatewayError(
                code="parse_llm_schema_invalid",
                message="llm response root must be object",
                retryable=False,
                provider_id=profile.provider_id,
                api_mode=profile.api_mode,
                http_status=response.status_code,
            )
        upstream_request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        logger.info(
            "llm_transport.ok request_id=%s source_id=%s task_name=%s provider_id=%s model=%s "
            "latency_ms=%s error_code=- retryable=- http_status=%s endpoint=%s",
            _ctx(request_context, "request_id"),
            _ctx(request_context, "source_id"),
            _ctx(request_context, "task_name"),
            profile.provider_id,
            profile.model,
            latency_ms,
            response.status_code,
            endpoint,
        )
        return response_json, latency_ms, upstream_request_id


def build_openai_compat_endpoint(*, base_url: str, api_mode: LlmApiModeLiteral) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ValueError("base_url is required")
    endpoint_suffix = "responses" if api_mode == "responses" else "chat/completions"

    if normalized.endswith(f"/{endpoint_suffix}"):
        return normalized
    if normalized.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")]
    if normalized.endswith("/responses"):
        normalized = normalized[: -len("/responses")]
    if normalized.endswith("/v1"):
        return f"{normalized}/{endpoint_suffix}"
    return f"{normalized}/v1/{endpoint_suffix}"


def _ctx(context: Mapping[str, object] | None, key: str) -> object:
    if context is None:
        return "-"
    value = context.get(key)
    return value if value is not None else "-"


def _merge_extra_body(*, payload: dict, profile: ResolvedLlmProfile) -> dict:
    if not profile.extra_body:
        return payload
    merged = dict(profile.extra_body)
    merged.update(payload)
    return merged
