from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select

from app.db.models.ingestion import ConnectorResultStatus, IngestResult
from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.review import (
    Change,
    ChangeType,
    EventEntity,
    EventEntityLifecycle,
    EventEntityLink,
    EventLinkOrigin,
    ReviewStatus,
    SourceEventObservation,
)
from app.db.models.shared import CourseWorkItemLabelFamily, IntegrationOutbox, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key
from app.modules.core_ingest.apply import apply_ingest_result_idempotent
from tests.support.payload_builders import build_course_parse, build_event_parts, build_gmail_payload, build_link_signals


def _create_user_source_and_family(db_session) -> tuple[User, InputSource, CourseWorkItemLabelFamily]:
    now = datetime.now(timezone.utc)
    user = User(
        email="gmail-dispatch-smoke@example.com",
        notify_email="gmail-dispatch-smoke@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key=f"gmail-dispatch-smoke-{user.id}",
        display_name="Gmail Dispatch Smoke",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    db_session.add(source)

    family = CourseWorkItemLabelFamily(
        user_id=user.id,
        course_dept="CSE",
        course_number=8,
        course_suffix="A",
        course_quarter="WI",
        course_year2=26,
        normalized_course_identity=normalized_course_identity_key(
            course_dept="CSE",
            course_number=8,
            course_suffix="A",
            course_quarter="WI",
            course_year2=26,
        ),
        canonical_label="Homework",
        normalized_canonical_label=normalize_label_token("Homework"),
    )
    db_session.add(family)
    db_session.commit()
    db_session.refresh(source)
    db_session.refresh(family)
    return user, source, family


def _seed_active_entity_for_directive(
    db_session,
    *,
    user_id: int,
    family_id: int,
    entity_uid: str,
) -> None:
    db_session.add(
        EventEntity(
            user_id=user_id,
            entity_uid=entity_uid,
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=8,
            course_suffix="A",
            course_quarter="WI",
            course_year2=26,
            family_id=family_id,
            raw_type="Homework",
            event_name="HW2",
            ordinal=2,
            due_date=date(2026, 3, 9),  # Monday
            due_time=None,
            time_precision="date_only",
        )
    )


def _seed_manual_link(
    db_session,
    *,
    user_id: int,
    source_id: int,
    external_event_id: str,
    entity_uid: str,
) -> None:
    db_session.add(
        EventEntityLink(
            user_id=user_id,
            source_id=source_id,
            source_kind=SourceKind.EMAIL,
            external_event_id=external_event_id,
            entity_uid=entity_uid,
            link_origin=EventLinkOrigin.MANUAL_CANDIDATE,
            link_score=1.0,
            signals_json={"seed": "manual_smoke_link"},
        )
    )


def _seed_ingest_result(
    db_session,
    *,
    source: InputSource,
    request_id: str,
    records: list[dict],
) -> None:
    db_session.add(
        SyncRequest(
            request_id=request_id,
            source_id=source.id,
            trigger_type=IngestTriggerType.MANUAL,
            status=SyncRequestStatus.RUNNING,
            idempotency_key=f"idemp:{request_id}",
            metadata_json={"kind": "test"},
        )
    )
    db_session.add(
        IngestResult(
            request_id=request_id,
            source_id=source.id,
            provider=source.provider,
            status=ConnectorResultStatus.CHANGED,
            cursor_patch={},
            records=records,
            fetched_at=datetime.now(timezone.utc),
            error_code=None,
            error_message=None,
        )
    )
    db_session.commit()


def _directive_record(*, message_id: str, external_event_id: str) -> dict:
    return {
        "record_type": "gmail.directive.extracted",
        "payload": {
            "message_id": message_id,
            "source_facts": {
                "external_event_id": external_event_id,
                "source_title": "Directive update",
                "source_summary": "Directive update summary",
                "from_header": "staff@example.edu",
                "thread_id": "thr-smoke-1",
                "internal_date": "2026-03-01T09:00:00+00:00",
            },
            "segment_index": 0,
            "segment_anchor": "seg-0",
            "segment_snippet": "move homework due date",
            "directive": {
                "selector": {
                    "course_dept": "CSE",
                    "course_number": 8,
                    "course_suffix": "A",
                    "course_quarter": "WI",
                    "course_year2": 26,
                    "family_hint": "Homework",
                    "raw_type_hint": "Homework",
                    "scope_mode": "ordinal_list",
                    "ordinal_list": [2],
                    "ordinal_range_start": None,
                    "ordinal_range_end": None,
                    "current_due_weekday": "monday",
                    "applies_to_future_only": False,
                },
                "mutation": {"move_weekday": "friday", "set_due_date": None},
                "confidence": 0.91,
                "evidence": "directive evidence",
            },
        },
    }


def test_gmail_mixed_dispatch_smoke_routes_atomic_and_directive_lanes(db_session) -> None:
    user, source, family = _create_user_source_and_family(db_session)
    _seed_active_entity_for_directive(
        db_session,
        user_id=user.id,
        family_id=family.id,
        entity_uid="ent-directive-1",
    )
    _seed_manual_link(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="msg-atomic-1",
        entity_uid="ent-atomic-1",
    )
    db_session.commit()

    atomic_record = {
        "record_type": "gmail.message.extracted",
        "payload": build_gmail_payload(
            message_id="msg-atomic-1",
            title="CSE8A HW1 Due",
            due_at=datetime(2026, 3, 11, 23, 59, tzinfo=timezone.utc),
            time_anchor_confidence=0.9,
            course_parse=build_course_parse(
                dept="CSE",
                number=8,
                suffix="A",
                quarter="WI",
                year2=26,
                confidence=0.92,
                evidence="CSE8A",
            ),
            event_parts=build_event_parts(type="deadline", index=1, confidence=0.9, evidence="HW1"),
            link_signals=build_link_signals(keywords=["homework", "deadline"]),
        ),
    }
    directive_record = _directive_record(
        message_id="msg-directive-1",
        external_event_id="msg-directive-1#directive-seg-0",
    )
    _seed_ingest_result(
        db_session,
        source=source,
        request_id="gmail-dispatch-smoke-1",
        records=[atomic_record, directive_record],
    )

    result = apply_ingest_result_idempotent(db_session, request_id="gmail-dispatch-smoke-1")
    assert result["applied"] is True
    assert result["idempotent_replay"] is False
    assert result["changes_created"] == 2

    atomic_observation = db_session.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.external_event_id == "msg-atomic-1",
            SourceEventObservation.is_active.is_(True),
        )
    )
    assert atomic_observation is not None
    assert atomic_observation.entity_uid == "ent-atomic-1"

    directive_observation_count = int(
        db_session.scalar(
            select(func.count(SourceEventObservation.id)).where(
                SourceEventObservation.source_id == source.id,
                SourceEventObservation.external_event_id == "msg-directive-1#directive-seg-0",
            )
        )
        or 0
    )
    assert directive_observation_count == 0

    pending_changes = list(
        db_session.scalars(
            select(Change).where(
                Change.user_id == user.id,
                Change.review_status == ReviewStatus.PENDING,
            ).order_by(Change.entity_uid.asc())
        ).all()
    )
    assert len(pending_changes) == 2
    by_entity_uid = {row.entity_uid: row for row in pending_changes}
    assert set(by_entity_uid) == {"ent-atomic-1", "ent-directive-1"}
    assert by_entity_uid["ent-atomic-1"].change_type == ChangeType.CREATED
    assert by_entity_uid["ent-directive-1"].change_type == ChangeType.DUE_CHANGED

    observed_source_refs = {
        ref.external_event_id
        for row in pending_changes
        for ref in row.source_refs
        if isinstance(ref.external_event_id, str) and ref.external_event_id
    }
    assert observed_source_refs == {"msg-atomic-1", "msg-directive-1#directive-seg-0"}

    outbox_rows = list(
        db_session.scalars(
            select(IntegrationOutbox).where(IntegrationOutbox.event_type == "review.pending.created").order_by(IntegrationOutbox.id.asc())
        ).all()
    )
    assert len(outbox_rows) == 2
    outbox_change_ids = {
        int(change_id)
        for row in outbox_rows
        for change_id in (row.payload_json.get("change_ids") if isinstance(row.payload_json, dict) else [])
    }
    assert outbox_change_ids == {int(row.id) for row in pending_changes}
