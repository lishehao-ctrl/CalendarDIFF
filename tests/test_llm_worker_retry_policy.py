from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.ingestion import IngestJob, IngestJobStatus
from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.shared import User
from app.modules.llm_runtime import transitions as llm_transitions


def _seed_claimed_context(db: Session, *, request_id: str) -> tuple[IngestJob, SyncRequest]:
    user = User(email=f"{request_id}@example.com", notify_email=f"{request_id}@example.com")
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

    sync = SyncRequest(
        request_id=request_id,
        source_id=source.id,
        trigger_type=IngestTriggerType.MANUAL,
        status=SyncRequestStatus.RUNNING,
        idempotency_key=request_id,
        metadata_json={},
    )
    db.add(sync)
    job = IngestJob(
        request_id=request_id,
        source_id=source.id,
        status=IngestJobStatus.CLAIMED,
        attempt=0,
        next_retry_at=datetime.now(timezone.utc),
        payload_json={"workflow_stage": "LLM_QUEUED"},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.refresh(sync)
    return job, sync


def test_retry_policy_schedules_retry(db_session: Session, monkeypatch) -> None:
    monkeypatch.setenv("LLM_MAX_RETRY_ATTEMPTS", "4")
    monkeypatch.setenv("LLM_RETRY_BASE_SECONDS", "1")
    monkeypatch.setenv("LLM_RETRY_MAX_SECONDS", "10")
    monkeypatch.setenv("LLM_RETRY_JITTER_SECONDS", "0")
    get_settings.cache_clear()
    try:
        job, sync = _seed_claimed_context(db_session, request_id="retry-ok")
        captured: dict[str, object] = {}

        def _capture_retry(*_args, **kwargs):  # noqa: ANN002, ANN003 - test hook
            captured.update(kwargs)

        monkeypatch.setattr(llm_transitions, "schedule_parse_retry", _capture_retry)
        monkeypatch.setattr(llm_transitions, "increment_parse_metric_counter", lambda *_args, **_kwargs: None)

        llm_transitions.apply_llm_failure_transition(
            db_session,
            redis_client=object(),  # type: ignore[arg-type]
            stream_key="llm:parse:stream",
            request_id=job.request_id,
            next_attempt=1,
            error_code="parse_llm_timeout",
            error_message="timeout",
            reason="parse_llm_timeout",
            retryable=True,
        )

        db_session.refresh(job)
        db_session.refresh(sync)
        assert job.status == IngestJobStatus.CLAIMED
        assert job.attempt == 1
        assert job.next_retry_at is not None
        assert sync.status == SyncRequestStatus.RUNNING
        assert sync.error_code == "parse_llm_timeout"
        assert captured["request_id"] == job.request_id
        assert captured["attempt"] == 1
    finally:
        get_settings.cache_clear()


def test_retry_policy_dead_letters_after_max_attempts(db_session: Session, monkeypatch) -> None:
    monkeypatch.setenv("LLM_MAX_RETRY_ATTEMPTS", "2")
    get_settings.cache_clear()
    try:
        job, sync = _seed_claimed_context(db_session, request_id="retry-dlq")
        llm_transitions.apply_llm_failure_transition(
            db_session,
            redis_client=object(),  # type: ignore[arg-type]
            stream_key="llm:parse:stream",
            request_id=job.request_id,
            next_attempt=2,
            error_code="parse_llm_timeout",
            error_message="timeout",
            reason="parse_llm_timeout",
            retryable=True,
        )

        db_session.refresh(job)
        db_session.refresh(sync)
        assert job.status == IngestJobStatus.DEAD_LETTER
        assert job.dead_lettered_at is not None
        assert sync.status == SyncRequestStatus.FAILED
        assert sync.error_code == "parse_llm_timeout"
    finally:
        get_settings.cache_clear()
