from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

LlmVendorLiteral = Literal["openai", "gemini", "dashscope_openai"]
LlmProtocolLiteral = Literal["chat_completions", "responses", "gemini_generate_content"]
SessionCacheModeLiteral = Literal["inherit", "enable", "disable"]
LlmProfileFamilyLiteral = Literal["ingestion", "agent", "helper", "judge"]
LlmStreamEventTypeLiteral = Literal["delta", "completed", "error"]


class LlmGatewayError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        provider_id: str | None,
        protocol: LlmProtocolLiteral | None,
        http_status: int | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.provider_id = provider_id
        self.protocol = protocol
        self.http_status = http_status
        super().__init__(message)


@dataclass(frozen=True)
class LlmInvokeRequest:
    task_name: str
    system_prompt: str
    user_payload: dict
    output_schema_name: str
    output_schema_json: dict
    profile_family: LlmProfileFamilyLiteral = "ingestion"
    source_id: int | None = None
    request_id: str | None = None
    source_provider: str | None = None
    temperature: float = 0.0
    shared_user_payload: dict | None = None
    cache_prefix_payload: dict | None = None
    cache_task_prompt: bool = False
    previous_response_id: str | None = None
    protocol_override: LlmProtocolLiteral | None = None
    session_cache_mode: SessionCacheModeLiteral = "inherit"


@dataclass(frozen=True)
class LlmStreamRequest:
    task_name: str
    system_prompt: str
    user_payload: dict
    profile_family: LlmProfileFamilyLiteral = "ingestion"
    source_id: int | None = None
    request_id: str | None = None
    source_provider: str | None = None
    temperature: float = 0.0
    shared_user_payload: dict | None = None
    cache_prefix_payload: dict | None = None
    previous_response_id: str | None = None
    protocol_override: LlmProtocolLiteral | None = None
    session_cache_mode: SessionCacheModeLiteral = "inherit"


@dataclass(frozen=True)
class LlmInvokeResult:
    json_object: dict
    provider_id: str
    protocol: LlmProtocolLiteral
    model: str
    latency_ms: int
    response_id: str | None = None
    upstream_request_id: str | None = None
    raw_usage: dict = field(default_factory=dict)
    route_id: str | None = None
    vendor: str | None = None


@dataclass(frozen=True)
class ResolvedLlmProfile:
    provider_id: str
    vendor: LlmVendorLiteral
    protocol: LlmProtocolLiteral
    base_url: str
    model: str
    api_key: str
    session_cache_enabled: bool
    timeout_seconds: float
    max_retries: int
    max_input_chars: int
    fallback_provider_ids: tuple[str, ...] = field(default_factory=tuple)
    extra_body: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LlmStreamEvent:
    event_type: LlmStreamEventTypeLiteral
    provider_id: str
    vendor: LlmVendorLiteral
    protocol: LlmProtocolLiteral
    model: str
    text_delta: str | None = None
    response_id: str | None = None
    upstream_request_id: str | None = None
    raw_usage: dict = field(default_factory=dict)
    vendor_event_type: str | None = None
    error_code: str | None = None
    error_message: str | None = None
