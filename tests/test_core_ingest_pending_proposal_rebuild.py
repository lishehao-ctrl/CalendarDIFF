from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeType, Event, Input, InputType, ReviewStatus, SourceEventObservation
from app.db.models.shared import IntegrationOutbox, User
from app.modules.core_ingest.pending_change_store import upsert_pending_change
from app.modules.core_ingest.pending_proposal_rebuild import rebuild_pending_change_proposals


def _seed_source_and_canonical_input(db_session) -> tuple[InputSource, Input]:
    now = datetime.now(timezone.utc)
    user = User(email="proposal-rebuild@example.com", notify_email="proposal-rebuild@example.com")
    db_session.add(user)
    db_session.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key=f"proposal-src-{user.id}",
        display_name="Proposal Source",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    db_session.add(source)
    db_session.flush()
    canonical_input = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key=f"canonical:user:{user.id}",
        is_active=True,
    )
    db_session.add(canonical_input)
    db_session.commit()
    db_session.refresh(source)
    db_session.refresh(canonical_input)
    return source, canonical_input


def _add_observation(
    db_session,
    *,
    source: InputSource,
    merge_key: str,
    external_event_id: str,
    start_at: datetime,
    end_at: datetime,
    title: str = "Exam",
    course_label: str = "CSE 100",
) -> SourceEventObservation:
    row = SourceEventObservation(
        user_id=source.user_id,
        source_id=source.id,
        source_kind=source.source_kind,
        provider=source.provider,
        external_event_id=external_event_id,
        merge_key=merge_key,
        event_payload={
            "source_canonical": {
                "source_dtstart_utc": start_at.isoformat(),
                "source_dtend_utc": end_at.isoformat(),
                "source_title": title,
            },
            "course_label": course_label,
            "confidence": 0.95,
        },
        event_hash="h" * 64,
        observed_at=datetime.now(timezone.utc),
        is_active=True,
        last_request_id="req-test",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _add_event(
    db_session,
    *,
    canonical_input: Input,
    uid: str,
    start_at: datetime,
    end_at: datetime,
    title: str = "Exam",
    course_label: str = "CSE 100",
) -> Event:
    row = Event(
        input_id=canonical_input.id,
        uid=uid,
        course_label=course_label,
        title=title,
        start_at_utc=start_at,
        end_at_utc=end_at,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_rebuild_creates_pending_change_and_emits_review_pending_outbox(db_session) -> None:
    source, canonical_input = _seed_source_and_canonical_input(db_session)
    start_at = datetime(2026, 3, 2, 18, 0, tzinfo=timezone.utc)
    _add_observation(
        db_session,
        source=source,
        merge_key="merge-create",
        external_event_id="obs-create-1",
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
    )
    db_session.commit()

    created_count, pending_event_uids = rebuild_pending_change_proposals(
        db=db_session,
        source=source,
        canonical_input=canonical_input,
        affected_merge_keys={"merge-create"},
        applied_at=datetime.now(timezone.utc),
    )
    db_session.commit()

    assert created_count == 1
    assert pending_event_uids == {"merge-create"}

    change = db_session.scalar(
        select(Change).where(
            Change.input_id == canonical_input.id,
            Change.event_uid == "merge-create",
            Change.review_status == ReviewStatus.PENDING,
        )
    )
    assert change is not None
    assert change.change_type == ChangeType.CREATED

    outbox_row = db_session.scalar(
        select(IntegrationOutbox).where(IntegrationOutbox.event_type == "review.pending.created")
    )
    assert outbox_row is not None
    payload = outbox_row.payload_json if isinstance(outbox_row.payload_json, dict) else {}
    assert payload.get("input_id") == canonical_input.id
    assert payload.get("change_ids") == [change.id]


def test_rebuild_rejects_pending_when_no_active_observation_and_no_event(db_session) -> None:
    source, canonical_input = _seed_source_and_canonical_input(db_session)
    now = datetime.now(timezone.utc)
    _ = upsert_pending_change(
        db=db_session,
        input_id=canonical_input.id,
        event_uid="merge-empty",
        change_type=ChangeType.CREATED,
        before_json=None,
        after_json={"uid": "merge-empty"},
        delta_seconds=None,
        proposal_merge_key="merge-empty",
        proposal_sources_json=[],
        detected_at=now,
    )
    db_session.commit()

    created_count, pending_event_uids = rebuild_pending_change_proposals(
        db=db_session,
        source=source,
        canonical_input=canonical_input,
        affected_merge_keys={"merge-empty"},
        applied_at=now + timedelta(minutes=1),
    )
    db_session.commit()

    assert created_count == 0
    assert pending_event_uids == {"merge-empty"}

    row = db_session.scalar(
        select(Change).where(
            Change.input_id == canonical_input.id,
            Change.event_uid == "merge-empty",
        )
    )
    assert row is not None
    assert row.review_status == ReviewStatus.REJECTED
    assert row.review_note == "proposal_resolved_no_active_observation"


def test_rebuild_creates_due_changed_and_removed_pending_changes(db_session) -> None:
    source, canonical_input = _seed_source_and_canonical_input(db_session)
    base_start = datetime(2026, 3, 3, 9, 0, tzinfo=timezone.utc)
    _add_event(
        db_session,
        canonical_input=canonical_input,
        uid="merge-due",
        start_at=base_start,
        end_at=base_start + timedelta(hours=1),
        title="Exam Due",
    )
    _add_observation(
        db_session,
        source=source,
        merge_key="merge-due",
        external_event_id="obs-due-1",
        start_at=base_start + timedelta(hours=2),
        end_at=base_start + timedelta(hours=3),
        title="Exam Due",
    )
    _add_event(
        db_session,
        canonical_input=canonical_input,
        uid="merge-removed",
        start_at=base_start,
        end_at=base_start + timedelta(hours=1),
        title="Exam Removed",
    )
    db_session.commit()

    created_count, pending_event_uids = rebuild_pending_change_proposals(
        db=db_session,
        source=source,
        canonical_input=canonical_input,
        affected_merge_keys={"merge-due", "merge-removed"},
        applied_at=datetime.now(timezone.utc),
    )
    db_session.commit()

    assert created_count == 2
    assert pending_event_uids == {"merge-due", "merge-removed"}

    due_change = db_session.scalar(
        select(Change).where(
            Change.input_id == canonical_input.id,
            Change.event_uid == "merge-due",
            Change.review_status == ReviewStatus.PENDING,
        )
    )
    removed_change = db_session.scalar(
        select(Change).where(
            Change.input_id == canonical_input.id,
            Change.event_uid == "merge-removed",
            Change.review_status == ReviewStatus.PENDING,
        )
    )
    assert due_change is not None
    assert due_change.change_type == ChangeType.DUE_CHANGED
    assert removed_change is not None
    assert removed_change.change_type == ChangeType.REMOVED


def test_rebuild_rejects_pending_when_payload_matches_canonical_event(db_session) -> None:
    source, canonical_input = _seed_source_and_canonical_input(db_session)
    start_at = datetime(2026, 3, 4, 10, 0, tzinfo=timezone.utc)
    _add_event(
        db_session,
        canonical_input=canonical_input,
        uid="merge-same",
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        title="Same Event",
    )
    _add_observation(
        db_session,
        source=source,
        merge_key="merge-same",
        external_event_id="obs-same-1",
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        title="Same Event",
    )
    _ = upsert_pending_change(
        db=db_session,
        input_id=canonical_input.id,
        event_uid="merge-same",
        change_type=ChangeType.DUE_CHANGED,
        before_json={"uid": "merge-same", "start_at_utc": "2026-03-04T08:00:00+00:00"},
        after_json={"uid": "merge-same", "start_at_utc": "2026-03-04T09:00:00+00:00"},
        delta_seconds=3600,
        proposal_merge_key="merge-same",
        proposal_sources_json=[],
        detected_at=datetime.now(timezone.utc),
    )
    db_session.commit()

    created_count, pending_event_uids = rebuild_pending_change_proposals(
        db=db_session,
        source=source,
        canonical_input=canonical_input,
        affected_merge_keys={"merge-same"},
        applied_at=datetime.now(timezone.utc),
    )
    db_session.commit()

    assert created_count == 0
    assert pending_event_uids == {"merge-same"}
    row = db_session.scalar(
        select(Change).where(
            Change.input_id == canonical_input.id,
            Change.event_uid == "merge-same",
        )
    )
    assert row is not None
    assert row.review_status == ReviewStatus.REJECTED
    assert row.review_note == "proposal_already_matches_canonical"


def test_rebuild_creates_pending_when_only_course_label_changes(db_session) -> None:
    source, canonical_input = _seed_source_and_canonical_input(db_session)
    start_at = datetime(2026, 3, 5, 10, 0, tzinfo=timezone.utc)
    _add_event(
        db_session,
        canonical_input=canonical_input,
        uid="merge-course-change",
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        title="Same Event",
        course_label="CSE 100",
    )
    _add_observation(
        db_session,
        source=source,
        merge_key="merge-course-change",
        external_event_id="obs-course-change-1",
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        title="Same Event",
        course_label="CSE 101",
    )
    db_session.commit()

    created_count, pending_event_uids = rebuild_pending_change_proposals(
        db=db_session,
        source=source,
        canonical_input=canonical_input,
        affected_merge_keys={"merge-course-change"},
        applied_at=datetime.now(timezone.utc),
    )
    db_session.commit()

    assert created_count == 1
    assert pending_event_uids == {"merge-course-change"}
    row = db_session.scalar(
        select(Change).where(
            Change.input_id == canonical_input.id,
            Change.event_uid == "merge-course-change",
            Change.review_status == ReviewStatus.PENDING,
        )
    )
    assert row is not None
    assert row.change_type == ChangeType.DUE_CHANGED
    assert isinstance(row.after_json, dict)
    assert row.after_json.get("course_label") == "CSE 101"
