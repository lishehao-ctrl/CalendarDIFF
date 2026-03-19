from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.shared import User
from app.modules.llm_gateway.contracts import LlmInvokeRequest, LlmInvokeResult
from app.modules.llm_gateway.usage_normalizer import normalize_llm_usage
from app.modules.llm_gateway.usage_tracking import LLM_USAGE_SUMMARY_KEY, record_sync_request_llm_usage


def test_normalize_llm_usage_reads_cache_and_reasoning_fields() -> None:
    normalized = normalize_llm_usage(
        {
            "input_tokens": 1524,
            "input_tokens_details": {"cached_tokens": 1305},
            "output_tokens": 1534,
            "output_tokens_details": {"reasoning_tokens": 1187},
            "total_tokens": 3058,
            "x_details": [
                {
                    "prompt_tokens_details": {
                        "cache_creation": {"ephemeral_5m_input_tokens": 213},
                        "cache_creation_input_tokens": 213,
                        "cached_tokens": 1305,
                    }
                }
            ],
        }
    )

    assert normalized == {
        "input_tokens": 1524,
        "cached_input_tokens": 1305,
        "cache_creation_input_tokens": 213,
        "output_tokens": 1534,
        "reasoning_tokens": 1187,
        "total_tokens": 3058,
    }


def test_record_sync_request_llm_usage_persists_summary_on_sync_request(db_session) -> None:
    user = User(
        notify_email="usage-tracking@example.com",
        password_hash="hash",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="usage-tracking-source",
        display_name="Usage Tracking Source",
        is_active=True,
        poll_interval_seconds=900,
    )
    db_session.add(source)
    db_session.flush()

    sync_request = SyncRequest(
        request_id="req-usage-1",
        source_id=source.id,
        trigger_type=IngestTriggerType.MANUAL,
        status=SyncRequestStatus.RUNNING,
        idempotency_key="usage-1",
        trace_id="usage-trace",
        metadata_json={"kind": "manual"},
    )
    db_session.add(sync_request)
    db_session.commit()

    request = LlmInvokeRequest(
        task_name="gmail_purpose_mode_classify",
        system_prompt="Return JSON object only.",
        user_payload={"message": {"subject": "hello"}},
        output_schema_name="AnyObject",
        output_schema_json={"type": "object"},
        source_id=source.id,
        request_id="req-usage-1",
        source_provider="gmail",
    )
    result = LlmInvokeResult(
        json_object={"mode": "atomic"},
        provider_id="env-default",
        model="qwen3.5-plus",
        api_mode="responses",
        latency_ms=420,
        response_id="resp-1",
        upstream_request_id="upstream-1",
        raw_usage={
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 700},
            "output_tokens": 120,
            "output_tokens_details": {"reasoning_tokens": 60},
            "total_tokens": 1120,
            "x_details": [
                {
                    "prompt_tokens_details": {
                        "cache_creation_input_tokens": 100,
                    }
                }
            ],
        },
    )

    record_sync_request_llm_usage(invoke_request=request, result=result)

    db_session.expire_all()
    refreshed = db_session.scalar(select(SyncRequest).where(SyncRequest.request_id == "req-usage-1"))
    assert refreshed is not None
    metadata = refreshed.metadata_json
    assert metadata["kind"] == "manual"
    summary = metadata[LLM_USAGE_SUMMARY_KEY]
    assert summary["successful_call_count"] == 1
    assert summary["usage_record_count"] == 1
    assert summary["latency_ms_total"] == 420
    assert summary["input_tokens"] == 1000
    assert summary["cached_input_tokens"] == 700
    assert summary["cache_creation_input_tokens"] == 100
    assert summary["output_tokens"] == 120
    assert summary["reasoning_tokens"] == 60
    assert summary["total_tokens"] == 1120
    assert summary["api_modes"] == {"responses": 1}
    assert summary["models"] == {"qwen3.5-plus": 1}
    assert summary["task_counts"] == {"gmail_purpose_mode_classify": 1}
