from __future__ import annotations

from sqlalchemy import select

from app.db.models.runtime import LlmInvocationLog
from app.modules.llm_gateway.tracing import LlmGatewayTraceEvent
from app.modules.llm_gateway.invocation_log import record_llm_invocation_trace


def test_record_llm_invocation_trace_persists_success_row(db_session) -> None:
    event = LlmGatewayTraceEvent(
        request_id="req-ledger-1",
        source_id=101,
        task_name="gmail_purpose_mode_classify",
        profile_family="ingestion",
        route_id="ingestion:env-default:responses:primary",
        route_index=1,
        route_count=1,
        is_fallback=False,
        provider_id="env-default",
        vendor="openai",
        model="test-model",
        protocol="responses",
        session_cache_enabled=True,
        success=True,
        latency_ms=123,
        upstream_request_id="upstream-1",
        response_id="resp-1",
        error_code=None,
        retryable=None,
        http_status=None,
        usage={"input_tokens": 10, "cached_input_tokens": 4, "cache_creation_input_tokens": 2, "output_tokens": 3, "reasoning_tokens": 0, "total_tokens": 13},
    )

    record_llm_invocation_trace(event=event)

    row = db_session.scalar(select(LlmInvocationLog).where(LlmInvocationLog.request_id == "req-ledger-1"))
    assert row is not None
    assert row.success is True
    assert row.protocol == "responses"
    assert row.route_id == "ingestion:env-default:responses:primary"
    assert row.usage_json["cached_input_tokens"] == 4


def test_record_llm_invocation_trace_persists_failure_row(db_session) -> None:
    event = LlmGatewayTraceEvent(
        request_id="req-ledger-2",
        source_id=102,
        task_name="calendar_semantic_extract",
        profile_family="ingestion",
        route_id="ingestion:env-default:chat_completions:fallback",
        route_index=2,
        route_count=2,
        is_fallback=True,
        provider_id="env-default",
        vendor="openai",
        model="fallback-model",
        protocol="chat_completions",
        session_cache_enabled=False,
        success=False,
        latency_ms=None,
        upstream_request_id=None,
        response_id=None,
        error_code="parse_llm_upstream_error",
        retryable=True,
        http_status=429,
        usage=None,
    )

    record_llm_invocation_trace(event=event)

    row = db_session.scalar(select(LlmInvocationLog).where(LlmInvocationLog.request_id == "req-ledger-2"))
    assert row is not None
    assert row.success is False
    assert row.protocol == "chat_completions"
    assert row.error_code == "parse_llm_upstream_error"
    assert row.http_status == 429
