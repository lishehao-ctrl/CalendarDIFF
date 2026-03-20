from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.runtime import ConnectorResultStatus, IngestJob, IngestJobStatus, IngestResult
from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.shared import User
from app.modules.runtime.connectors.connector_runtime import process_claimed_job
from app.modules.runtime.connectors.connector_types import ConnectorFetchOutcome


def _seed_claimed_job(db: Session, *, request_id: str, provider: str = "gmail") -> tuple[IngestJob, SyncRequest]:
    user = User(email=f"{request_id}@example.com", notify_email=f"{request_id}@example.com")
    db.add(user)
    db.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL if provider == "gmail" else SourceKind.CALENDAR,
        provider=provider,
        source_key=f"src-{request_id}",
        display_name=f"src-{request_id}",
        is_active=True,
        poll_interval_seconds=900,
    )
    db.add(source)
    db.flush()
    sync_request = SyncRequest(
        request_id=request_id,
        source_id=source.id,
        trigger_type=IngestTriggerType.MANUAL,
        status=SyncRequestStatus.RUNNING,
        idempotency_key=request_id,
        metadata_json={},
    )
    db.add(sync_request)
    job = IngestJob(
        request_id=request_id,
        source_id=source.id,
        status=IngestJobStatus.CLAIMED,
        attempt=0,
        next_retry_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        payload_json={"workflow_stage": "CLAIMED"},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.refresh(sync_request)
    return job, sync_request


def test_process_claimed_job_marks_llm_enqueue_pending_without_queue(db_session: Session, monkeypatch) -> None:
    job, sync_request = _seed_claimed_job(db_session, request_id="proc-pending")
    commit_calls = {"count": 0}
    original_commit = db_session.commit

    def _commit_spy():
        commit_calls["count"] += 1
        return original_commit()

    monkeypatch.setattr(db_session, "commit", _commit_spy)
    monkeypatch.setattr(
        "app.modules.runtime.connectors.connector_runtime.dispatch_provider_fetch",
        lambda **_kwargs: ConnectorFetchOutcome(
            status=ConnectorResultStatus.CHANGED,
            cursor_patch={"history_id": "h1"},
            parse_payload={"kind": "gmail", "messages": [{"message_id": "m1"}]},
            error_code=None,
            error_message=None,
        ),
    )

    assert process_claimed_job(db_session, job_id=job.id) is True
    assert commit_calls["count"] == 1
    db_session.refresh(job)
    db_session.refresh(sync_request)
    payload = job.payload_json if isinstance(job.payload_json, dict) else {}
    assert payload.get("workflow_stage") == "LLM_ENQUEUE_PENDING"
    assert sync_request.status == SyncRequestStatus.RUNNING
    assert db_session.scalar(select(IngestResult).where(IngestResult.request_id == sync_request.request_id)) is None


def test_process_claimed_job_success_without_parse_writes_result(db_session: Session, monkeypatch) -> None:
    job, sync_request = _seed_claimed_job(db_session, request_id="proc-success")
    monkeypatch.setattr(
        "app.modules.runtime.connectors.connector_runtime.dispatch_provider_fetch",
        lambda **_kwargs: ConnectorFetchOutcome(
            status=ConnectorResultStatus.NO_CHANGE,
            cursor_patch={"history_id": "h2"},
            parse_payload=None,
            error_code=None,
            error_message=None,
        ),
    )
    assert process_claimed_job(db_session, job_id=job.id) is True
    db_session.refresh(job)
    db_session.refresh(sync_request)
    assert job.status == IngestJobStatus.SUCCEEDED
    assert sync_request.status == SyncRequestStatus.SUCCEEDED
    result = db_session.scalar(select(IngestResult).where(IngestResult.request_id == sync_request.request_id))
    assert result is not None


def test_process_claimed_job_failure_uses_retry_policy(db_session: Session, monkeypatch) -> None:
    job, sync_request = _seed_claimed_job(db_session, request_id="proc-failure")
    monkeypatch.setattr(
        "app.modules.runtime.connectors.connector_runtime.dispatch_provider_fetch",
        lambda **_kwargs: ConnectorFetchOutcome(
            status=ConnectorResultStatus.FETCH_FAILED,
            cursor_patch={},
            parse_payload=None,
            error_code="gmail_fetch_failed",
            error_message="upstream timeout",
        ),
    )
    assert process_claimed_job(db_session, job_id=job.id) is True
    db_session.refresh(job)
    db_session.refresh(sync_request)
    assert job.status == IngestJobStatus.PENDING
    assert sync_request.status == SyncRequestStatus.QUEUED
    assert sync_request.error_code == "gmail_fetch_failed"
