from __future__ import annotations

import json

import httpx

from app.core.config import Settings
from app.modules.ingestion.llm_parsers.contracts import LlmParseError


class IngestionLlmClient:
    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings
        self._timeout = httpx.Timeout(
            connect=settings.http_connect_timeout_seconds,
            read=settings.ingestion_llm_timeout_seconds,
            write=settings.ingestion_llm_timeout_seconds,
            pool=settings.http_connect_timeout_seconds,
        )

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        if not self._settings.ingestion_llm_enabled:
            raise LlmParseError(
                code="parse_llm_upstream_error",
                message="ingestion llm is disabled",
                retryable=False,
                provider="unknown",
                parser_version="v2",
            )
        if not self._settings.ingestion_llm_base_url or not self._settings.ingestion_llm_api_key:
            raise LlmParseError(
                code="parse_llm_upstream_error",
                message="ingestion llm base url or api key is missing",
                retryable=False,
                provider="unknown",
                parser_version="v2",
            )

        request_payload = {
            "model": self._settings.ingestion_llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        attempts = max(int(self._settings.ingestion_llm_max_retries), 0) + 1
        last_error: LlmParseError | None = None
        for _ in range(attempts):
            try:
                response_json = self._post_chat_completions(request_payload)
                return self._extract_json_content(response_json)
            except LlmParseError as exc:
                last_error = exc
                if not exc.retryable:
                    break
        assert last_error is not None
        raise last_error

    def _post_chat_completions(self, request_payload: dict) -> dict:
        url = _build_chat_completions_url(self._settings.ingestion_llm_base_url)
        headers = {
            "Authorization": f"Bearer {self._settings.ingestion_llm_api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                response = client.post(url, headers=headers, json=request_payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LlmParseError(
                code="parse_llm_timeout",
                message=f"ingestion llm timeout: {exc}",
                retryable=True,
                provider="unknown",
                parser_version="v2",
            ) from exc
        except (httpx.NetworkError, httpx.HTTPStatusError) as exc:
            raise LlmParseError(
                code="parse_llm_upstream_error",
                message=f"ingestion llm upstream error: {exc}",
                retryable=True,
                provider="unknown",
                parser_version="v2",
            ) from exc

        try:
            parsed = response.json()
        except Exception as exc:
            raise LlmParseError(
                code="parse_llm_schema_invalid",
                message="ingestion llm response is not valid json",
                retryable=False,
                provider="unknown",
                parser_version="v2",
            ) from exc
        if not isinstance(parsed, dict):
            raise LlmParseError(
                code="parse_llm_schema_invalid",
                message="ingestion llm response root must be object",
                retryable=False,
                provider="unknown",
                parser_version="v2",
            )
        return parsed

    def _extract_json_content(self, response_json: dict) -> dict:
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LlmParseError(
                code="parse_llm_schema_invalid",
                message="ingestion llm response missing choices",
                retryable=False,
                provider="unknown",
                parser_version="v2",
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise LlmParseError(
                code="parse_llm_schema_invalid",
                message="ingestion llm choice payload invalid",
                retryable=False,
                provider="unknown",
                parser_version="v2",
            )

        message = first.get("message")
        if not isinstance(message, dict):
            raise LlmParseError(
                code="parse_llm_schema_invalid",
                message="ingestion llm message payload invalid",
                retryable=False,
                provider="unknown",
                parser_version="v2",
            )
        content = message.get("content")
        text_content = _extract_text_content(content)
        if text_content is None:
            raise LlmParseError(
                code="parse_llm_empty_output",
                message="ingestion llm returned empty content",
                retryable=False,
                provider="unknown",
                parser_version="v2",
            )
        try:
            parsed = json.loads(text_content)
        except json.JSONDecodeError as exc:
            raise LlmParseError(
                code="parse_llm_schema_invalid",
                message="ingestion llm content is not valid json",
                retryable=False,
                provider="unknown",
                parser_version="v2",
            ) from exc
        if not isinstance(parsed, dict):
            raise LlmParseError(
                code="parse_llm_schema_invalid",
                message="ingestion llm content root must be object",
                retryable=False,
                provider="unknown",
                parser_version="v2",
            )
        return parsed


def _extract_text_content(content: object) -> str | None:
    if isinstance(content, str):
        stripped = content.strip()
        return stripped or None
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
        if chunks:
            return "\n".join(chunks)
    return None


def _build_chat_completions_url(base_url: str | None) -> str:
    if not base_url or not base_url.strip():
        raise ValueError("ingestion_llm_base_url is required")
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"
