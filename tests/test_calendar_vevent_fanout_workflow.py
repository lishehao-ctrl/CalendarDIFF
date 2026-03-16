from __future__ import annotations

import base64
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models.ingestion import (
    CalendarComponentParseStatus,
    CalendarComponentParseTask,
    ConnectorResultStatus,
    IngestJob,
    IngestJobStatus,
    IngestResult,
)
from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.shared import User
from app.modules.ingestion.calendar_fanout_contract import CALENDAR_REDUCE_REASON
from app.modules.ingestion.connector_dispatch import dispatch_pending_llm_enqueues
from app.modules.llm_runtime.message_processor import process_parse_task_message
from app.modules.llm_runtime.parse_pipeline import RateLimitRejected
from app.modules.runtime_kernel.parse_task_queue import ParseTaskMessage


def _vevent_component(*, uid: str, recurrence_id: str | None, summary: str) -> dict:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
    ]
    if recurrence_id is not None:
        lines.append(f"RECURRENCE-ID:{recurrence_id}")
    lines.extend(
        [
            "DTSTART:20260301T100000Z",
            "DTEND:20260301T110000Z",
            f"SUMMARY:{summary}",
            "END:VEVENT",
        ]
    )
    component_text = "\n".join(lines)
    component_ical_b64 = base64.b64encode(component_text.encode("utf-8")).decode("ascii")
    component_key = f"{uid}#{(recurrence_id or '').strip()}"
    external_event_id = uid if not recurrence_id else f"{uid}#{recurrence_id}"
    return {
        "component_key": component_key,
        "external_event_id": external_event_id,
        "fingerprint": f"fp-{uid}-{recurrence_id or 'main'}",
        "component_ical_b64": component_ical_b64,
    }


def _seed_calendar_job(
    db: Session,
    *,
    request_id: str,
    parse_payload: dict,
    workflow_stage: str,
    job_status: IngestJobStatus,
) -> tuple[InputSource, SyncRequest, IngestJob]:
    user = User(email=f"{request_id}@example.com", notify_email=f"{request_id}@example.com")
    db.add(user)
    db.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
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
        status=job_status,
        attempt=0,
        next_retry_at=datetime.now(timezone.utc),
        payload_json={
            "workflow_stage": workflow_stage,
            "provider": "ics",
            "llm_parse_payload": parse_payload,
            "llm_cursor_patch": {"etag": "etag-1"},
            "llm_enqueue_dispatch_attempt": 0,
        },
    )
    db.add(job)
    db.commit()
    db.refresh(source)
    db.refresh(sync_request)
    db.refresh(job)
    return source, sync_request, job


def _dispatch_calendar_job(db_session: Session, monkeypatch, *, request_id: str, parse_payload: dict) -> tuple[InputSource, SyncRequest, IngestJob, list[dict]]:
    source, sync_request, job = _seed_calendar_job(
        db_session,
        request_id=request_id,
        parse_payload=parse_payload,
        workflow_stage="LLM_ENQUEUE_PENDING",
        job_status=IngestJobStatus.CLAIMED,
    )
    enqueued: list[dict] = []
    monkeypatch.setattr("app.modules.ingestion.connector_dispatch.get_parse_queue_redis_client", lambda: object())
    monkeypatch.setattr("app.modules.ingestion.connector_dispatch.ensure_parse_queue_group", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "app.modules.ingestion.connector_dispatch.enqueue_parse_task",
        lambda **kwargs: enqueued.append(dict(kwargs)) or f"msg-{len(enqueued)}",
    )
    dispatched = dispatch_pending_llm_enqueues(db_session)
    assert dispatched == 1
    db_session.refresh(job)
    db_session.refresh(sync_request)
    return source, sync_request, job, enqueued


def test_calendar_fanout_dispatch_creates_child_tasks_and_reduce_queue(db_session: Session, monkeypatch) -> None:
    parse_payload = {
        "kind": "calendar_delta",
        "changed_components": [
            _vevent_component(uid="evt-main", recurrence_id=None, summary="HW1"),
            _vevent_component(uid="evt-rid", recurrence_id="20260301T100000Z", summary="Quiz"),
        ],
        "removed_component_keys": ["evt-remove#"],
    }
    source, _sync_request, job, enqueued = _dispatch_calendar_job(
        db_session,
        monkeypatch,
        request_id="fanout-dispatch-1",
        parse_payload=parse_payload,
    )

    reasons = [row["reason"] for row in enqueued]
    assert CALENDAR_REDUCE_REASON in reasons
    assert "calendar_component:evt-main#" in reasons
    assert "calendar_component:evt-rid#20260301T100000Z" in reasons

    rows = list(
        db_session.scalars(
            select(CalendarComponentParseTask)
            .where(CalendarComponentParseTask.request_id == "fanout-dispatch-1")
            .order_by(CalendarComponentParseTask.component_key.asc())
        ).all()
    )
    assert len(rows) == 2
    assert all(row.source_id == source.id for row in rows)
    assert all(row.status == CalendarComponentParseStatus.PENDING for row in rows)
    rid_row = next(row for row in rows if row.component_key.endswith("20260301T100000Z"))
    assert rid_row.vevent_uid == "evt-rid"
    assert rid_row.recurrence_id == "20260301T100000Z"

    payload = job.payload_json if isinstance(job.payload_json, dict) else {}
    assert payload.get("workflow_stage") == "LLM_CALENDAR_FANOUT_QUEUED"
    assert int(payload.get("calendar_child_task_count") or 0) == 2


def test_calendar_fanout_end_to_end_component_success_then_reduce(db_session: Session, db_session_factory: sessionmaker, monkeypatch) -> None:
    parse_payload = {
        "kind": "calendar_delta",
        "changed_components": [_vevent_component(uid="evt-success", recurrence_id=None, summary="HW2")],
        "removed_component_keys": ["evt-remove#"],
    }
    source, sync_request, _job, enqueued = _dispatch_calendar_job(
        db_session,
        monkeypatch,
        request_id="fanout-e2e-1",
        parse_payload=parse_payload,
    )
    component_reason = next(row["reason"] for row in enqueued if str(row["reason"]).startswith("calendar_component:"))

    monkeypatch.setattr(
        "app.modules.llm_runtime.calendar_fanout.parse_calendar_changed_component_with_llm",
        lambda **_kwargs: [
            {
                "record_type": "calendar.event.extracted",
                "payload": {
                    "source_facts": {
                        "external_event_id": "evt-success",
                        "component_key": "evt-success#",
                        "source_title": "HW2",
                        "source_dtstart_utc": "2026-03-01T10:00:00+00:00",
                        "source_dtend_utc": "2026-03-01T11:00:00+00:00",
                    },
                    "semantic_event_draft": {
                        "course_dept": "CSE",
                        "course_number": 8,
                        "raw_type": "Homework",
                        "event_name": "HW2",
                        "ordinal": 2,
                        "due_date": "2026-03-01",
                        "due_time": "10:00:00",
                        "time_precision": "datetime",
                        "confidence": 0.9,
                        "evidence": "HW2",
                    },
                    "link_signals": {},
                    "component_key": "evt-success#",
                    "raw_ics_component_b64": parse_payload["changed_components"][0]["component_ical_b64"],
                },
            }
        ],
    )
    monkeypatch.setattr(
        "app.modules.llm_runtime.calendar_fanout.enqueue_parse_task",
        lambda **_kwargs: "msg-reduce",
    )

    component_ack = process_parse_task_message(
        message=ParseTaskMessage(
            message_id="msg-component-1",
            request_id="fanout-e2e-1",
            source_id=source.id,
            attempt=0,
            reason=component_reason,
        ),
        redis_client=object(),  # type: ignore[arg-type]
        session_factory=db_session_factory,
        worker_id="llm-worker-test",
        stream_key="llm:parse:stream",
    )
    assert component_ack is True

    task_row = db_session.scalar(
        select(CalendarComponentParseTask).where(
            CalendarComponentParseTask.request_id == "fanout-e2e-1",
            CalendarComponentParseTask.component_key == "evt-success#",
        )
    )
    assert task_row is not None
    assert task_row.status == CalendarComponentParseStatus.SUCCEEDED
    assert isinstance(task_row.parsed_record_json, dict)

    reduce_ack = process_parse_task_message(
        message=ParseTaskMessage(
            message_id="msg-reduce-1",
            request_id="fanout-e2e-1",
            source_id=source.id,
            attempt=0,
            reason=CALENDAR_REDUCE_REASON,
        ),
        redis_client=object(),  # type: ignore[arg-type]
        session_factory=db_session_factory,
        worker_id="llm-worker-test",
        stream_key="llm:parse:stream",
    )
    assert reduce_ack is True

    result = db_session.scalar(select(IngestResult).where(IngestResult.request_id == "fanout-e2e-1"))
    assert result is not None
    assert result.status == ConnectorResultStatus.CHANGED
    assert isinstance(result.records, list)
    assert len(result.records) == 2
    assert any(row.get("record_type") == "calendar.event.removed" for row in result.records)
    assert any(row.get("record_type") == "calendar.event.extracted" for row in result.records)
    db_session.refresh(sync_request)
    assert sync_request.status == SyncRequestStatus.RUNNING
    db_session.refresh(source)
    assert source.cursor is None


def test_calendar_fanout_rate_limited_component_requeues_without_failing(db_session: Session, db_session_factory: sessionmaker, monkeypatch) -> None:
    parse_payload = {
        "kind": "calendar_delta",
        "changed_components": [_vevent_component(uid="evt-rate", recurrence_id=None, summary="HW3")],
        "removed_component_keys": [],
    }
    source, _sync_request, _job, enqueued = _dispatch_calendar_job(
        db_session,
        monkeypatch,
        request_id="fanout-rate-limit-1",
        parse_payload=parse_payload,
    )
    component_reason = next(row["reason"] for row in enqueued if str(row["reason"]).startswith("calendar_component:"))
    scheduled: list[dict] = []

    monkeypatch.setattr(
        "app.modules.llm_runtime.calendar_fanout.parse_calendar_changed_component_with_llm",
        lambda **_kwargs: (_ for _ in ()).throw(RateLimitRejected(reason="target_cap")),
    )
    monkeypatch.setattr(
        "app.modules.llm_runtime.calendar_fanout.schedule_parse_retry",
        lambda **kwargs: scheduled.append(dict(kwargs)),
    )

    component_ack = process_parse_task_message(
        message=ParseTaskMessage(
            message_id="msg-component-rate-1",
            request_id="fanout-rate-limit-1",
            source_id=source.id,
            attempt=0,
            reason=component_reason,
        ),
        redis_client=object(),  # type: ignore[arg-type]
        session_factory=db_session_factory,
        worker_id="llm-worker-test",
        stream_key="llm:parse:stream",
    )
    assert component_ack is True

    task_row = db_session.scalar(
        select(CalendarComponentParseTask).where(
            CalendarComponentParseTask.request_id == "fanout-rate-limit-1",
            CalendarComponentParseTask.component_key == "evt-rate#",
        )
    )
    assert task_row is not None
    assert task_row.status == CalendarComponentParseStatus.PENDING
    assert task_row.attempt == 0
    assert task_row.error_code == "llm_rate_limited"
    assert scheduled and scheduled[0]["request_id"] == "fanout-rate-limit-1"


def test_calendar_fanout_removed_only_skips_child_and_reducer_commits(db_session: Session, db_session_factory: sessionmaker, monkeypatch) -> None:
    parse_payload = {
        "kind": "calendar_delta",
        "changed_components": [],
        "removed_component_keys": ["evt-remove#"],
    }
    source, sync_request, _job, enqueued = _dispatch_calendar_job(
        db_session,
        monkeypatch,
        request_id="fanout-removed-only-1",
        parse_payload=parse_payload,
    )
    assert [row["reason"] for row in enqueued] == [CALENDAR_REDUCE_REASON]
    row_count = int(
        db_session.scalar(
            select(func.count(CalendarComponentParseTask.id)).where(CalendarComponentParseTask.request_id == "fanout-removed-only-1")
        )
        or 0
    )
    assert row_count == 0

    ack = process_parse_task_message(
        message=ParseTaskMessage(
            message_id="msg-reduce-removed-only",
            request_id="fanout-removed-only-1",
            source_id=source.id,
            attempt=0,
            reason=CALENDAR_REDUCE_REASON,
        ),
        redis_client=object(),  # type: ignore[arg-type]
        session_factory=db_session_factory,
        worker_id="llm-worker-test",
        stream_key="llm:parse:stream",
    )
    assert ack is True

    result = db_session.scalar(select(IngestResult).where(IngestResult.request_id == "fanout-removed-only-1"))
    assert result is not None
    assert result.status == ConnectorResultStatus.CHANGED
    assert result.records == [
        {
            "record_type": "calendar.event.removed",
            "payload": {"component_key": "evt-remove#", "external_event_id": "evt-remove"},
        }
    ]
    db_session.refresh(sync_request)
    assert sync_request.status == SyncRequestStatus.RUNNING
    db_session.refresh(source)
    assert source.cursor is None


def test_calendar_fanout_component_unresolved_is_persisted_and_reducer_waits_for_terminal(
    db_session: Session,
    db_session_factory: sessionmaker,
    monkeypatch,
) -> None:
    broken_component = _vevent_component(uid="evt-broken", recurrence_id=None, summary="Broken")
    broken_component["component_ical_b64"] = "not-base64"
    parse_payload = {
        "kind": "calendar_delta",
        "changed_components": [broken_component],
        "removed_component_keys": [],
    }
    source, _sync_request, _job, enqueued = _dispatch_calendar_job(
        db_session,
        monkeypatch,
        request_id="fanout-unresolved-1",
        parse_payload=parse_payload,
    )
    component_reason = next(row["reason"] for row in enqueued if str(row["reason"]).startswith("calendar_component:"))
    monkeypatch.setattr(
        "app.modules.llm_runtime.calendar_fanout.enqueue_parse_task",
        lambda **_kwargs: "msg-reduce-unresolved",
    )

    component_ack = process_parse_task_message(
        message=ParseTaskMessage(
            message_id="msg-component-unresolved",
            request_id="fanout-unresolved-1",
            source_id=source.id,
            attempt=0,
            reason=component_reason,
        ),
        redis_client=object(),  # type: ignore[arg-type]
        session_factory=db_session_factory,
        worker_id="llm-worker-test",
        stream_key="llm:parse:stream",
    )
    assert component_ack is True

    task_row = db_session.scalar(
        select(CalendarComponentParseTask).where(
            CalendarComponentParseTask.request_id == "fanout-unresolved-1",
            CalendarComponentParseTask.component_key == "evt-broken#",
        )
    )
    assert task_row is not None
    assert task_row.status == CalendarComponentParseStatus.UNRESOLVED
    assert task_row.error_code == "llm_calendar_delta_payload_invalid"

    reduce_ack = process_parse_task_message(
        message=ParseTaskMessage(
            message_id="msg-reduce-unresolved",
            request_id="fanout-unresolved-1",
            source_id=source.id,
            attempt=0,
            reason=CALENDAR_REDUCE_REASON,
        ),
        redis_client=object(),  # type: ignore[arg-type]
        session_factory=db_session_factory,
        worker_id="llm-worker-test",
        stream_key="llm:parse:stream",
    )
    assert reduce_ack is True

    result = db_session.scalar(select(IngestResult).where(IngestResult.request_id == "fanout-unresolved-1"))
    assert result is not None
    assert result.status == ConnectorResultStatus.NO_CHANGE
    assert result.records == []


def test_calendar_fanout_reducer_waits_until_all_children_terminal(
    db_session: Session,
    db_session_factory: sessionmaker,
    monkeypatch,
) -> None:
    parse_payload = {
        "kind": "calendar_delta",
        "changed_components": [
            _vevent_component(uid="evt-a", recurrence_id=None, summary="A"),
            _vevent_component(uid="evt-b", recurrence_id=None, summary="B"),
        ],
        "removed_component_keys": [],
    }
    source, _sync_request, _job, _enqueued = _dispatch_calendar_job(
        db_session,
        monkeypatch,
        request_id="fanout-reduce-wait-1",
        parse_payload=parse_payload,
    )
    task_a = db_session.scalar(
        select(CalendarComponentParseTask).where(
            CalendarComponentParseTask.request_id == "fanout-reduce-wait-1",
            CalendarComponentParseTask.component_key == "evt-a#",
        )
    )
    task_b = db_session.scalar(
        select(CalendarComponentParseTask).where(
            CalendarComponentParseTask.request_id == "fanout-reduce-wait-1",
            CalendarComponentParseTask.component_key == "evt-b#",
        )
    )
    assert task_a is not None and task_b is not None
    task_a.status = CalendarComponentParseStatus.SUCCEEDED
    task_a.parsed_record_json = {
        "record_type": "calendar.event.extracted",
        "payload": {
            "source_facts": {
                "external_event_id": "evt-a",
                "component_key": "evt-a#",
                "source_title": "A",
                "source_dtstart_utc": "2026-03-01T10:00:00+00:00",
                "source_dtend_utc": "2026-03-01T11:00:00+00:00",
            },
            "semantic_event_draft": {},
            "link_signals": {},
        },
    }
    task_b.status = CalendarComponentParseStatus.PENDING
    db_session.commit()

    first_reduce_ack = process_parse_task_message(
        message=ParseTaskMessage(
            message_id="msg-reduce-wait-1",
            request_id="fanout-reduce-wait-1",
            source_id=source.id,
            attempt=0,
            reason=CALENDAR_REDUCE_REASON,
        ),
        redis_client=object(),  # type: ignore[arg-type]
        session_factory=db_session_factory,
        worker_id="llm-worker-test",
        stream_key="llm:parse:stream",
    )
    assert first_reduce_ack is True
    assert db_session.scalar(select(IngestResult).where(IngestResult.request_id == "fanout-reduce-wait-1")) is None

    task_b = db_session.scalar(
        select(CalendarComponentParseTask).where(
            CalendarComponentParseTask.request_id == "fanout-reduce-wait-1",
            CalendarComponentParseTask.component_key == "evt-b#",
        )
    )
    assert task_b is not None
    task_b.status = CalendarComponentParseStatus.FAILED
    task_b.error_code = "parse_llm_worker_exception"
    task_b.error_message = "boom"
    db_session.commit()

    second_reduce_ack = process_parse_task_message(
        message=ParseTaskMessage(
            message_id="msg-reduce-wait-2",
            request_id="fanout-reduce-wait-1",
            source_id=source.id,
            attempt=0,
            reason=CALENDAR_REDUCE_REASON,
        ),
        redis_client=object(),  # type: ignore[arg-type]
        session_factory=db_session_factory,
        worker_id="llm-worker-test",
        stream_key="llm:parse:stream",
    )
    assert second_reduce_ack is True
    result = db_session.scalar(select(IngestResult).where(IngestResult.request_id == "fanout-reduce-wait-1"))
    assert result is not None
    assert result.status == ConnectorResultStatus.CHANGED
    assert len(result.records) == 1
