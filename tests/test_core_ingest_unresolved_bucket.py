from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.ingestion import ConnectorResultStatus, IngestResult, IngestUnresolvedRecord
from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.review import Change, EventEntityLink, EventLinkCandidate, SourceEventObservation
from app.db.models.shared import IntegrationOutbox, User
from app.modules.core_ingest.apply import apply_ingest_result_idempotent
from tests.support.payload_builders import (
    build_calendar_payload,
    build_course_parse,
    build_gmail_payload,
    build_semantic_parse,
)


def _create_source(
    db_session: Session,
    *,
    source_kind: SourceKind,
    provider: str,
    source_key: str,
) -> tuple[User, InputSource]:
    now = datetime.now(timezone.utc)
    user = User(
        email=f"{provider}-owner@example.com",
        notify_email=f"{provider}-owner@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=source_kind,
        provider=provider,
        source_key=source_key,
        display_name=f"{provider} Source",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return user, source


def _seed_result(
    db_session: Session,
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


def test_valid_calendar_ingest_assigns_non_null_family_id(db_session: Session) -> None:
    _user, source = _create_source(
        db_session,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="valid-family-id-source",
    )
    due_at = datetime(2026, 3, 20, 23, 59, tzinfo=timezone.utc)
    payload = build_calendar_payload(
        external_event_id="evt-valid-family",
        title="Reading Reflection",
        start_at=due_at,
        end_at=due_at + timedelta(hours=1),
        course_parse=build_course_parse(dept="CSE", number=120, quarter="WI", year2=26, confidence=0.9, evidence="CSE120"),
        semantic_parse=build_semantic_parse(
            raw_type=None,
            event_name="Reading Reflection",
            ordinal=1,
            due_at=due_at,
            confidence=0.8,
            evidence="reflection",
        ),
    )
    _seed_result(
        db_session,
        source=source,
        request_id="valid-family-id-1",
        records=[{"record_type": "calendar.event.extracted", "payload": payload}],
    )

    apply_result = apply_ingest_result_idempotent(db_session, request_id="valid-family-id-1")
    assert apply_result["changes_created"] == 1

    observation = db_session.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.external_event_id == "evt-valid-family",
        )
    )
    assert observation is not None
    semantic_event = observation.event_payload.get("semantic_event") if isinstance(observation.event_payload, dict) else {}
    assert isinstance(semantic_event.get("family_id"), int)
    unresolved_count = db_session.scalar(select(func.count(IngestUnresolvedRecord.id)).where(IngestUnresolvedRecord.source_id == source.id))
    assert int(unresolved_count or 0) == 0


def test_missing_course_identity_isolated_to_unresolved_bucket_without_review_side_effects(db_session: Session) -> None:
    user, source = _create_source(
        db_session,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="missing-course-identity-source",
    )
    due_at = datetime(2026, 3, 21, 18, 0, tzinfo=timezone.utc)
    payload = build_calendar_payload(
        external_event_id="evt-unresolved-calendar",
        title="Homework Missing Course",
        start_at=due_at,
        end_at=due_at + timedelta(hours=1),
        course_parse=build_course_parse(confidence=0.1, evidence="missing"),
    )
    _seed_result(
        db_session,
        source=source,
        request_id="unresolved-calendar-1",
        records=[{"record_type": "calendar.event.extracted", "payload": payload}],
    )

    apply_result = apply_ingest_result_idempotent(db_session, request_id="unresolved-calendar-1")
    assert apply_result["changes_created"] == 0

    unresolved = db_session.scalar(
        select(IngestUnresolvedRecord).where(
            IngestUnresolvedRecord.source_id == source.id,
            IngestUnresolvedRecord.external_event_id == "evt-unresolved-calendar",
            IngestUnresolvedRecord.is_active.is_(True),
        )
    )
    assert unresolved is not None
    assert unresolved.reason_code == "missing_course_identity"
    assert unresolved.source_facts_json.get("external_event_id") == "evt-unresolved-calendar"

    observation_count = db_session.scalar(select(func.count(SourceEventObservation.id)).where(SourceEventObservation.source_id == source.id))
    change_count = db_session.scalar(select(func.count(Change.id)).where(Change.user_id == user.id))
    outbox_count = db_session.scalar(
        select(func.count(IntegrationOutbox.id)).where(
            IntegrationOutbox.event_type == "review.pending.created",
            IntegrationOutbox.aggregate_type == "change_batch",
        )
    )
    assert int(observation_count or 0) == 0
    assert int(change_count or 0) == 0
    assert int(outbox_count or 0) == 0


def test_missing_course_identity_for_gmail_creates_no_link_side_effects(db_session: Session) -> None:
    user, source = _create_source(
        db_session,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="missing-course-identity-gmail-source",
    )
    due_at = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)
    payload = build_gmail_payload(
        message_id="msg-unresolved-gmail",
        title="Project Reminder Without Course",
        due_at=due_at,
        course_parse=build_course_parse(confidence=0.1, evidence="missing"),
    )
    _seed_result(
        db_session,
        source=source,
        request_id="unresolved-gmail-1",
        records=[{"record_type": "gmail.message.extracted", "payload": payload}],
    )

    apply_result = apply_ingest_result_idempotent(db_session, request_id="unresolved-gmail-1")
    assert apply_result["changes_created"] == 0

    unresolved = db_session.scalar(
        select(IngestUnresolvedRecord).where(
            IngestUnresolvedRecord.source_id == source.id,
            IngestUnresolvedRecord.external_event_id == "msg-unresolved-gmail",
            IngestUnresolvedRecord.is_active.is_(True),
        )
    )
    assert unresolved is not None
    assert unresolved.reason_code == "missing_course_identity"

    observation_count = db_session.scalar(select(func.count(SourceEventObservation.id)).where(SourceEventObservation.source_id == source.id))
    change_count = db_session.scalar(select(func.count(Change.id)).where(Change.user_id == user.id))
    candidate_count = db_session.scalar(select(func.count(EventLinkCandidate.id)).where(EventLinkCandidate.user_id == user.id))
    link_count = db_session.scalar(select(func.count(EventEntityLink.id)).where(EventEntityLink.user_id == user.id))
    outbox_count = db_session.scalar(
        select(func.count(IntegrationOutbox.id)).where(
            IntegrationOutbox.event_type == "review.pending.created",
            IntegrationOutbox.aggregate_type == "change_batch",
        )
    )
    assert int(observation_count or 0) == 0
    assert int(change_count or 0) == 0
    assert int(candidate_count or 0) == 0
    assert int(link_count or 0) == 0
    assert int(outbox_count or 0) == 0


def test_later_valid_ingest_resolves_active_unresolved_record(db_session: Session) -> None:
    user, source = _create_source(
        db_session,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="unresolved-recovery-source",
    )
    due_at = datetime(2026, 3, 23, 20, 0, tzinfo=timezone.utc)

    unresolved_payload = build_calendar_payload(
        external_event_id="evt-recover",
        title="Recoverable Homework",
        start_at=due_at,
        end_at=due_at + timedelta(hours=1),
        course_parse=build_course_parse(confidence=0.1, evidence="missing"),
    )
    _seed_result(
        db_session,
        source=source,
        request_id="recover-unresolved-1",
        records=[{"record_type": "calendar.event.extracted", "payload": unresolved_payload}],
    )
    first_apply = apply_ingest_result_idempotent(db_session, request_id="recover-unresolved-1")
    assert first_apply["changes_created"] == 0

    valid_payload = build_calendar_payload(
        external_event_id="evt-recover",
        title="Recoverable Homework",
        start_at=due_at,
        end_at=due_at + timedelta(hours=1),
        course_parse=build_course_parse(dept="CSE", number=140, quarter="SP", year2=26, confidence=0.95, evidence="CSE140"),
    )
    _seed_result(
        db_session,
        source=source,
        request_id="recover-valid-1",
        records=[{"record_type": "calendar.event.extracted", "payload": valid_payload}],
    )
    second_apply = apply_ingest_result_idempotent(db_session, request_id="recover-valid-1")
    assert second_apply["changes_created"] == 1

    unresolved_rows = list(
        db_session.scalars(
            select(IngestUnresolvedRecord).where(
                IngestUnresolvedRecord.source_id == source.id,
                IngestUnresolvedRecord.external_event_id == "evt-recover",
            )
        ).all()
    )
    assert len(unresolved_rows) == 1
    assert unresolved_rows[0].is_active is False
    assert unresolved_rows[0].resolved_at is not None

    observation = db_session.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.external_event_id == "evt-recover",
        )
    )
    assert observation is not None
    semantic_event = observation.event_payload.get("semantic_event") if isinstance(observation.event_payload, dict) else {}
    assert isinstance(semantic_event.get("family_id"), int)

    change_count = db_session.scalar(select(func.count(Change.id)).where(Change.user_id == user.id))
    outbox_count = db_session.scalar(
        select(func.count(IntegrationOutbox.id)).where(
            IntegrationOutbox.event_type == "review.pending.created",
            IntegrationOutbox.aggregate_type == "change_batch",
        )
    )
    assert int(change_count or 0) == 1
    assert int(outbox_count or 0) == 1


def test_calendar_valid_to_unresolved_retires_active_observation_without_semantic_side_effects(db_session: Session) -> None:
    user, source = _create_source(
        db_session,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="transition-calendar-source",
    )
    due_at = datetime(2026, 3, 24, 22, 0, tzinfo=timezone.utc)
    valid_payload = build_calendar_payload(
        external_event_id="evt-transition-calendar",
        title="Transition Homework",
        start_at=due_at,
        end_at=due_at + timedelta(hours=1),
        course_parse=build_course_parse(dept="CSE", number=150, quarter="SP", year2=26, confidence=0.95, evidence="CSE150"),
    )
    _seed_result(
        db_session,
        source=source,
        request_id="transition-calendar-valid",
        records=[{"record_type": "calendar.event.extracted", "payload": valid_payload}],
    )
    apply_ingest_result_idempotent(db_session, request_id="transition-calendar-valid")

    baseline_change_count = int(
        db_session.scalar(select(func.count(Change.id)).where(Change.user_id == user.id)) or 0
    )
    baseline_outbox_count = int(
        db_session.scalar(
            select(func.count(IntegrationOutbox.id)).where(
                IntegrationOutbox.event_type == "review.pending.created",
                IntegrationOutbox.aggregate_type == "change_batch",
            )
        )
        or 0
    )

    unresolved_payload = build_calendar_payload(
        external_event_id="evt-transition-calendar",
        title="Transition Homework Missing Course",
        start_at=due_at,
        end_at=due_at + timedelta(hours=1),
        course_parse=build_course_parse(confidence=0.1, evidence="missing"),
    )
    _seed_result(
        db_session,
        source=source,
        request_id="transition-calendar-unresolved",
        records=[{"record_type": "calendar.event.extracted", "payload": unresolved_payload}],
    )
    second_apply = apply_ingest_result_idempotent(db_session, request_id="transition-calendar-unresolved")
    assert second_apply["changes_created"] == 0

    active_observation_count = int(
        db_session.scalar(
            select(func.count(SourceEventObservation.id)).where(
                SourceEventObservation.source_id == source.id,
                SourceEventObservation.external_event_id == "evt-transition-calendar",
                SourceEventObservation.is_active.is_(True),
            )
        )
        or 0
    )
    assert active_observation_count == 0

    unresolved_active = db_session.scalar(
        select(IngestUnresolvedRecord).where(
            IngestUnresolvedRecord.source_id == source.id,
            IngestUnresolvedRecord.external_event_id == "evt-transition-calendar",
            IngestUnresolvedRecord.is_active.is_(True),
        )
    )
    assert unresolved_active is not None
    assert unresolved_active.reason_code == "missing_course_identity"

    current_change_count = int(
        db_session.scalar(select(func.count(Change.id)).where(Change.user_id == user.id)) or 0
    )
    current_outbox_count = int(
        db_session.scalar(
            select(func.count(IntegrationOutbox.id)).where(
                IntegrationOutbox.event_type == "review.pending.created",
                IntegrationOutbox.aggregate_type == "change_batch",
            )
        )
        or 0
    )
    assert current_change_count == baseline_change_count
    assert current_outbox_count == baseline_outbox_count


def test_gmail_valid_to_unresolved_retires_active_observation_without_semantic_side_effects(db_session: Session) -> None:
    user, source = _create_source(
        db_session,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="transition-gmail-source",
    )
    due_at = datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc)
    valid_payload = build_gmail_payload(
        message_id="msg-transition-gmail",
        title="Transition Gmail Homework",
        due_at=due_at,
        course_parse=build_course_parse(dept="CSE", number=152, quarter="SP", year2=26, confidence=0.92, evidence="CSE152"),
    )
    _seed_result(
        db_session,
        source=source,
        request_id="transition-gmail-valid",
        records=[{"record_type": "gmail.message.extracted", "payload": valid_payload}],
    )
    apply_ingest_result_idempotent(db_session, request_id="transition-gmail-valid")

    baseline_change_count = int(
        db_session.scalar(select(func.count(Change.id)).where(Change.user_id == user.id)) or 0
    )
    baseline_outbox_count = int(
        db_session.scalar(
            select(func.count(IntegrationOutbox.id)).where(
                IntegrationOutbox.event_type == "review.pending.created",
                IntegrationOutbox.aggregate_type == "change_batch",
            )
        )
        or 0
    )
    baseline_candidate_count = int(
        db_session.scalar(select(func.count(EventLinkCandidate.id)).where(EventLinkCandidate.user_id == user.id)) or 0
    )
    baseline_link_count = int(
        db_session.scalar(select(func.count(EventEntityLink.id)).where(EventEntityLink.user_id == user.id)) or 0
    )

    unresolved_payload = build_gmail_payload(
        message_id="msg-transition-gmail",
        title="Transition Gmail Homework Missing Course",
        due_at=due_at,
        course_parse=build_course_parse(confidence=0.1, evidence="missing"),
    )
    _seed_result(
        db_session,
        source=source,
        request_id="transition-gmail-unresolved",
        records=[{"record_type": "gmail.message.extracted", "payload": unresolved_payload}],
    )
    second_apply = apply_ingest_result_idempotent(db_session, request_id="transition-gmail-unresolved")
    assert second_apply["changes_created"] == 0

    active_observation_count = int(
        db_session.scalar(
            select(func.count(SourceEventObservation.id)).where(
                SourceEventObservation.source_id == source.id,
                SourceEventObservation.external_event_id == "msg-transition-gmail",
                SourceEventObservation.is_active.is_(True),
            )
        )
        or 0
    )
    assert active_observation_count == 0

    unresolved_active = db_session.scalar(
        select(IngestUnresolvedRecord).where(
            IngestUnresolvedRecord.source_id == source.id,
            IngestUnresolvedRecord.external_event_id == "msg-transition-gmail",
            IngestUnresolvedRecord.is_active.is_(True),
        )
    )
    assert unresolved_active is not None
    assert unresolved_active.reason_code == "missing_course_identity"

    current_change_count = int(
        db_session.scalar(select(func.count(Change.id)).where(Change.user_id == user.id)) or 0
    )
    current_outbox_count = int(
        db_session.scalar(
            select(func.count(IntegrationOutbox.id)).where(
                IntegrationOutbox.event_type == "review.pending.created",
                IntegrationOutbox.aggregate_type == "change_batch",
            )
        )
        or 0
    )
    current_candidate_count = int(
        db_session.scalar(select(func.count(EventLinkCandidate.id)).where(EventLinkCandidate.user_id == user.id)) or 0
    )
    current_link_count = int(
        db_session.scalar(select(func.count(EventEntityLink.id)).where(EventEntityLink.user_id == user.id)) or 0
    )
    assert current_change_count == baseline_change_count
    assert current_outbox_count == baseline_outbox_count
    assert current_candidate_count == baseline_candidate_count
    assert current_link_count == baseline_link_count


def test_calendar_removed_record_clears_active_unresolved_entry(db_session: Session) -> None:
    user, source = _create_source(
        db_session,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="unresolved-remove-source",
    )
    due_at = datetime(2026, 3, 24, 19, 0, tzinfo=timezone.utc)
    unresolved_payload = build_calendar_payload(
        external_event_id="evt-remove-unresolved",
        title="Unresolved Removal Target",
        start_at=due_at,
        end_at=due_at + timedelta(hours=1),
        course_parse=build_course_parse(confidence=0.1, evidence="missing"),
    )
    _seed_result(
        db_session,
        source=source,
        request_id="remove-unresolved-seed",
        records=[{"record_type": "calendar.event.extracted", "payload": unresolved_payload}],
    )
    first_apply = apply_ingest_result_idempotent(db_session, request_id="remove-unresolved-seed")
    assert first_apply["changes_created"] == 0

    _seed_result(
        db_session,
        source=source,
        request_id="remove-unresolved-clear",
        records=[
            {
                "record_type": "calendar.event.removed",
                "payload": {
                    "external_event_id": "evt-remove-unresolved",
                    "component_key": "evt-remove-unresolved#",
                },
            }
        ],
    )
    second_apply = apply_ingest_result_idempotent(db_session, request_id="remove-unresolved-clear")
    assert second_apply["changes_created"] == 0

    unresolved_rows = list(
        db_session.scalars(
            select(IngestUnresolvedRecord).where(
                IngestUnresolvedRecord.source_id == source.id,
                IngestUnresolvedRecord.external_event_id == "evt-remove-unresolved",
            )
        ).all()
    )
    assert len(unresolved_rows) == 1
    assert unresolved_rows[0].is_active is False
    assert unresolved_rows[0].resolved_at is not None

    observation_count = db_session.scalar(select(func.count(SourceEventObservation.id)).where(SourceEventObservation.source_id == source.id))
    change_count = db_session.scalar(select(func.count(Change.id)).where(Change.user_id == user.id))
    outbox_count = db_session.scalar(
        select(func.count(IntegrationOutbox.id)).where(
            IntegrationOutbox.event_type == "review.pending.created",
            IntegrationOutbox.aggregate_type == "change_batch",
        )
    )
    assert int(observation_count or 0) == 0
    assert int(change_count or 0) == 0
    assert int(outbox_count or 0) == 0
