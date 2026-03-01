from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


LlmApiModeLiteral = Literal["chat_completions", "responses"]


class LlmGatewayError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        provider_id: str | None,
        api_mode: LlmApiModeLiteral | None,
        http_status: int | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.provider_id = provider_id
        self.api_mode = api_mode
        self.http_status = http_status
        super().__init__(message)


@dataclass(frozen=True)
class LlmInvokeRequest:
    task_name: str
    system_prompt: str
    user_payload: dict
    output_schema_name: str
    output_schema_json: dict
    source_id: int | None = None
    request_id: str | None = None
    source_provider: str | None = None
    llm_provider_id: str | None = None
    temperature: float = 0.0


@dataclass(frozen=True)
class LlmInvokeResult:
    json_object: dict
    provider_id: str
    model: str
    api_mode: LlmApiModeLiteral
    latency_ms: int
    upstream_request_id: str | None = None
    raw_usage: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedLlmProfile:
    provider_id: str
    vendor: str
    base_url: str
    api_mode: LlmApiModeLiteral
    model: str
    api_key: str
    timeout_seconds: float
    max_retries: int
    max_input_chars: int
