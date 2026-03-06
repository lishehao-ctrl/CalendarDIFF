from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.ingestion import IngestJob, IngestJobStatus
from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.shared import User
from app.modules.llm_runtime.message_preflight import prepare_message_for_processing
from app.modules.runtime_kernel.parse_task_queue import ParseTaskMessage


def test_prepare_message_for_processing_marks_llm_running(db_session) -> None:
    user = User(email="preflight@example.com", notify_email="preflight@example.com")
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="preflight-src",
        display_name="preflight-src",
        is_active=True,
        poll_interval_seconds=900,
    )
    db_session.add(source)
    db_session.flush()

    sync = SyncRequest(
        request_id="preflight-req",
        source_id=source.id,
        trigger_type=IngestTriggerType.MANUAL,
        status=SyncRequestStatus.RUNNING,
        idempotency_key="preflight-req",
        metadata_json={},
    )
    db_session.add(sync)

    job = IngestJob(
        request_id="preflight-req",
        source_id=source.id,
        status=IngestJobStatus.CLAIMED,
        attempt=0,
        next_retry_at=datetime.now(timezone.utc),
        payload_json={
            "workflow_stage": "LLM_QUEUED",
            "provider": "gmail",
            "llm_parse_payload": {"kind": "gmail", "messages": [{"message_id": "m1"}]},
            "llm_cursor_patch": {"history_id": "h-1"},
        },
    )
    db_session.add(job)
    db_session.commit()

    result = prepare_message_for_processing(
        db_session,
        message=ParseTaskMessage(
            message_id="msg-1",
            request_id="preflight-req",
            source_id=source.id,
            attempt=0,
            reason="initial",
        ),
        worker_id="llm-worker-test",
    )

    db_session.refresh(job)
    assert result.should_parse is True
    assert result.provider_hint == "gmail"
    payload = job.payload_json if isinstance(job.payload_json, dict) else {}
    assert payload.get("workflow_stage") == "LLM_RUNNING"
    assert payload.get("llm_worker_id") == "llm-worker-test"
