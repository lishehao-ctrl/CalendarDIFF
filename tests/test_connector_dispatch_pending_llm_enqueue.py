from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models.runtime import IngestJob, IngestJobStatus
from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.shared import User
from app.modules.runtime.connectors.connector_dispatch import dispatch_pending_llm_enqueues


def _seed_pending_enqueue_job(db: Session, *, request_id: str, dispatch_attempt: int = 0) -> tuple[IngestJob, SyncRequest]:
    user = User(email=f"{request_id}@example.com")
    db.add(user)
    db.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
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
    payload = {
        "workflow_stage": "LLM_ENQUEUE_PENDING",
        "provider": "gmail",
        "llm_parse_payload": {"kind": "gmail", "messages": [{"message_id": "m1"}]},
        "llm_cursor_patch": {"history_id": "h-1"},
        "llm_enqueue_dispatch_attempt": dispatch_attempt,
    }
    job = IngestJob(
        request_id=request_id,
        source_id=source.id,
        status=IngestJobStatus.CLAIMED,
        attempt=0,
        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        payload_json=payload,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.refresh(sync_request)
    return job, sync_request


def test_dispatch_pending_enqueue_success_marks_queued(db_session: Session, monkeypatch) -> None:
    job, sync_request = _seed_pending_enqueue_job(db_session, request_id="dispatch-ok")
    captured: dict[str, object] = {}

    monkeypatch.setattr("app.modules.runtime.connectors.connector_dispatch.get_parse_queue_redis_client", lambda: object())
    monkeypatch.setattr("app.modules.runtime.connectors.connector_dispatch.ensure_parse_queue_group", lambda *_args, **_kwargs: None)

    def _enqueue(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return "msg-id-1"

    monkeypatch.setattr("app.modules.runtime.connectors.connector_dispatch.enqueue_parse_task", _enqueue)
    dispatched = dispatch_pending_llm_enqueues(db_session)
    assert dispatched == 1

    db_session.refresh(job)
    db_session.refresh(sync_request)
    payload = job.payload_json if isinstance(job.payload_json, dict) else {}
    assert payload.get("workflow_stage") == "LLM_QUEUED"
    assert payload.get("llm_enqueued_at")
    assert sync_request.status == SyncRequestStatus.RUNNING
    assert captured["request_id"] == "dispatch-ok"


def test_dispatch_pending_enqueue_failure_keeps_pending_before_threshold(db_session: Session, monkeypatch) -> None:
    job, sync_request = _seed_pending_enqueue_job(db_session, request_id="dispatch-fail-pending")

    monkeypatch.setattr("app.modules.runtime.connectors.connector_dispatch.get_parse_queue_redis_client", lambda: object())
    monkeypatch.setattr("app.modules.runtime.connectors.connector_dispatch.ensure_parse_queue_group", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "app.modules.runtime.connectors.connector_dispatch.enqueue_parse_task",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
    )

    dispatched = dispatch_pending_llm_enqueues(db_session)
    assert dispatched == 0
    db_session.refresh(job)
    db_session.refresh(sync_request)
    payload = job.payload_json if isinstance(job.payload_json, dict) else {}
    assert payload.get("workflow_stage") == "LLM_ENQUEUE_PENDING"
    assert int(payload.get("llm_enqueue_dispatch_attempt") or 0) == 1
    assert payload.get("llm_enqueue_last_error")
    assert sync_request.status == SyncRequestStatus.RUNNING


def test_dispatch_pending_enqueue_failure_reaches_threshold_and_retries_connector(db_session: Session, monkeypatch) -> None:
    job, sync_request = _seed_pending_enqueue_job(db_session, request_id="dispatch-fail-threshold", dispatch_attempt=2)

    monkeypatch.setattr("app.modules.runtime.connectors.connector_dispatch.get_parse_queue_redis_client", lambda: object())
    monkeypatch.setattr("app.modules.runtime.connectors.connector_dispatch.ensure_parse_queue_group", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "app.modules.runtime.connectors.connector_dispatch.enqueue_parse_task",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
    )

    dispatched = dispatch_pending_llm_enqueues(db_session)
    assert dispatched == 0
    db_session.refresh(job)
    db_session.refresh(sync_request)
    assert job.status == IngestJobStatus.PENDING
    assert sync_request.status == SyncRequestStatus.QUEUED
    assert sync_request.error_code == "llm_queue_unavailable"


def test_dispatch_pending_enqueue_ignores_future_next_retry_for_llm_pending(db_session: Session, monkeypatch) -> None:
    job, sync_request = _seed_pending_enqueue_job(db_session, request_id="dispatch-future-next-retry")
    job.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    db_session.commit()
    captured: dict[str, object] = {}

    monkeypatch.setattr("app.modules.runtime.connectors.connector_dispatch.get_parse_queue_redis_client", lambda: object())
    monkeypatch.setattr("app.modules.runtime.connectors.connector_dispatch.ensure_parse_queue_group", lambda *_args, **_kwargs: None)

    def _enqueue(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return "msg-id-future"

    monkeypatch.setattr("app.modules.runtime.connectors.connector_dispatch.enqueue_parse_task", _enqueue)
    dispatched = dispatch_pending_llm_enqueues(db_session)
    assert dispatched == 1

    db_session.refresh(job)
    db_session.refresh(sync_request)
    payload = job.payload_json if isinstance(job.payload_json, dict) else {}
    assert payload.get("workflow_stage") == "LLM_QUEUED"
    assert payload.get("llm_enqueued_at")
    assert sync_request.status == SyncRequestStatus.RUNNING
    assert captured["request_id"] == "dispatch-future-next-retry"
