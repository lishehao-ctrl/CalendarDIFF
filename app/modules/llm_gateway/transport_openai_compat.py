from __future__ import annotations

import time

import httpx

from app.modules.llm_gateway.contracts import LlmGatewayError, ResolvedLlmProfile


class OpenAICompatTransport:
    def post_json(self, *, profile: ResolvedLlmProfile, payload: dict) -> tuple[dict, int, str | None]:
        attempts = max(int(profile.max_retries), 0) + 1
        last_error: LlmGatewayError | None = None
        for _ in range(attempts):
            try:
                return self._post_json_once(profile=profile, payload=payload)
            except LlmGatewayError as exc:
                last_error = exc
                if not exc.retryable:
                    break
        assert last_error is not None
        raise last_error

    def _post_json_once(self, *, profile: ResolvedLlmProfile, payload: dict) -> tuple[dict, int, str | None]:
        endpoint = build_openai_compat_endpoint(base_url=profile.base_url)
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
                response = client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LlmGatewayError(
                code="parse_llm_timeout",
                message=f"llm request timeout: {exc}",
                retryable=True,
                provider_id=profile.provider_id,
                api_mode=profile.api_mode,
            ) from exc
        except httpx.NetworkError as exc:
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
            raise LlmGatewayError(
                code="parse_llm_schema_invalid",
                message="llm response is not valid json",
                retryable=False,
                provider_id=profile.provider_id,
                api_mode=profile.api_mode,
                http_status=response.status_code,
            ) from exc
        if not isinstance(response_json, dict):
            raise LlmGatewayError(
                code="parse_llm_schema_invalid",
                message="llm response root must be object",
                retryable=False,
                provider_id=profile.provider_id,
                api_mode=profile.api_mode,
                http_status=response.status_code,
            )
        upstream_request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        return response_json, latency_ms, upstream_request_id


def build_openai_compat_endpoint(*, base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ValueError("base_url is required")
    endpoint_suffix = "chat/completions"

    if normalized.endswith(f"/{endpoint_suffix}"):
        return normalized
    if normalized.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")]
    if normalized.endswith("/v1"):
        return f"{normalized}/{endpoint_suffix}"
    return f"{normalized}/v1/{endpoint_suffix}"
