from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeType, EventEntity, EventEntityLifecycle, ReviewStatus, SourceEventObservation
from app.db.models.shared import CourseWorkItemLabelFamily, IntegrationOutbox, User
from app.modules.runtime.apply.pending_proposal_rebuild import rebuild_pending_change_proposals


def _semantic_payload(
    *,
    uid: str,
    family_name: str,
    event_name: str,
    due_at: datetime,
    family_id: int,
    raw_type: str | None = None,
) -> dict:
    return {
        "uid": uid,
        "course_dept": "CSE",
        "course_number": 100,
        "course_quarter": "WI",
        "course_year2": 26,
        "family_id": family_id,
        "family_name": family_name,
        "raw_type": raw_type or family_name,
        "event_name": event_name,
        "ordinal": 1,
        "due_date": due_at.date().isoformat(),
        "due_time": due_at.timetz().replace(tzinfo=None).isoformat(),
        "time_precision": "datetime",
    }


def _seed_source(db_session) -> InputSource:
    user = User(email="rebuild@example.com")
    db_session.add(user)
    db_session.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key=f"ics-{user.id}",
        display_name="Calendar",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def _add_observation(
    db_session,
    *,
    source: InputSource,
    entity_uid: str,
    external_event_id: str,
    due_at: datetime,
    family_name: str = "Homework",
    family_id: int,
    raw_type: str | None = None,
    is_active: bool = True,
) -> None:
    semantic = _semantic_payload(
        uid=entity_uid,
        family_name=family_name,
        event_name="Homework 1",
        due_at=due_at,
        family_id=family_id,
        raw_type=raw_type,
    )
    db_session.add(
        SourceEventObservation(
            user_id=source.user_id,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id=external_event_id,
            entity_uid=entity_uid,
            event_payload={
                "source_facts": {
                    "external_event_id": external_event_id,
                    "source_title": "Homework 1",
                    "source_summary": "Homework summary",
                    "source_dtstart_utc": due_at.isoformat(),
                    "source_dtend_utc": (due_at + timedelta(hours=1)).isoformat(),
                },
                "semantic_event": semantic,
            },
            event_hash="0" * 64,
            observed_at=datetime.now(timezone.utc),
            is_active=is_active,
            last_request_id="req-rebuild",
        )
    )
    db_session.flush()


def test_rebuild_creates_pending_change_and_outbox_for_new_entity(db_session) -> None:
    source = _seed_source(db_session)
    family = CourseWorkItemLabelFamily(
        user_id=source.user_id,
        course_dept="CSE",
        course_number=100,
        course_quarter="WI",
        course_year2=26,
        normalized_course_identity="cse:100::wi:26",
        canonical_label="Homework",
        normalized_canonical_label="homework",
    )
    db_session.add(family)
    db_session.flush()
    due_at = datetime(2026, 3, 18, 23, 59, tzinfo=timezone.utc)
    _add_observation(
        db_session,
        source=source,
        entity_uid="ent-created",
        external_event_id="evt-created",
        due_at=due_at,
        family_id=family.id,
    )
    db_session.commit()

    created_count, pending_entity_uids = rebuild_pending_change_proposals(
        db=db_session,
        user_id=source.user_id,
        source=source,
        affected_entity_uids={"ent-created"},
        applied_at=datetime.now(timezone.utc),
    )
    db_session.commit()

    assert created_count == 1
    assert pending_entity_uids == {"ent-created"}

    change = db_session.scalar(select(Change).where(Change.user_id == source.user_id, Change.entity_uid == "ent-created"))
    assert change is not None
    assert change.change_type == ChangeType.CREATED
    assert len(change.source_refs) == 1
    assert change.source_refs[0].source_id == source.id
    assert change.source_refs[0].source_kind == SourceKind.CALENDAR
    assert change.source_refs[0].provider == "ics"
    assert change.source_refs[0].external_event_id == "evt-created"
    outbox = db_session.scalar(select(IntegrationOutbox).where(IntegrationOutbox.event_type == "changes.pending.created"))
    assert outbox is not None
    payload = outbox.payload_json
    assert payload["user_id"] == source.user_id
    assert payload["change_ids"] == [change.id]


def test_rebuild_creates_due_changed_and_removed_against_active_entity_state(db_session) -> None:
    source = _seed_source(db_session)
    family = CourseWorkItemLabelFamily(
        user_id=source.user_id,
        course_dept="CSE",
        course_number=100,
        course_quarter="WI",
        course_year2=26,
        normalized_course_identity="cse:100::wi:26",
        canonical_label="Homework",
        normalized_canonical_label="homework",
    )
    db_session.add(family)
    db_session.flush()
    base_due = datetime(2026, 3, 20, 18, 0, tzinfo=timezone.utc)
    changed_due = base_due + timedelta(hours=2)
    db_session.add_all(
        [
            EventEntity(
                user_id=source.user_id,
                entity_uid="ent-due",
                lifecycle=EventEntityLifecycle.ACTIVE,
                course_dept="CSE",
                course_number=100,
                course_quarter="WI",
                course_year2=26,
                family_id=family.id,
                raw_type="Homework",
                event_name="Homework 1",
                ordinal=1,
                due_date=base_due.date(),
                due_time=base_due.timetz().replace(tzinfo=None),
                time_precision="datetime",
            ),
            EventEntity(
                user_id=source.user_id,
                entity_uid="ent-removed",
                lifecycle=EventEntityLifecycle.ACTIVE,
                course_dept="CSE",
                course_number=100,
                course_quarter="WI",
                course_year2=26,
                family_id=family.id,
                raw_type="Homework",
                event_name="Homework 1",
                ordinal=1,
                due_date=base_due.date(),
                due_time=base_due.timetz().replace(tzinfo=None),
                time_precision="datetime",
            ),
        ]
    )
    _add_observation(
        db_session,
        source=source,
        entity_uid="ent-due",
        external_event_id="evt-due",
        due_at=changed_due,
        family_id=family.id,
    )
    _add_observation(
        db_session,
        source=source,
        entity_uid="ent-removed",
        external_event_id="evt-removed",
        due_at=base_due,
        family_id=family.id,
        is_active=False,
    )
    db_session.commit()

    created_count, pending_entity_uids = rebuild_pending_change_proposals(
        db=db_session,
        user_id=source.user_id,
        source=source,
        affected_entity_uids={"ent-due", "ent-removed"},
        applied_at=datetime.now(timezone.utc),
    )
    db_session.commit()

    assert created_count == 2
    assert pending_entity_uids == {"ent-due", "ent-removed"}

    due_change = db_session.scalar(
        select(Change).where(Change.user_id == source.user_id, Change.entity_uid == "ent-due", Change.review_status == ReviewStatus.PENDING)
    )
    removed_change = db_session.scalar(
        select(Change).where(Change.user_id == source.user_id, Change.entity_uid == "ent-removed", Change.review_status == ReviewStatus.PENDING)
    )
    assert due_change is not None and due_change.change_type == ChangeType.DUE_CHANGED
    assert removed_change is not None and removed_change.change_type == ChangeType.REMOVED
    assert len(removed_change.source_refs) == 1
    assert removed_change.source_refs[0].source_id == source.id
    assert removed_change.source_refs[0].external_event_id == "evt-removed"


def test_rebuild_treats_family_id_as_authority_when_family_label_is_renamed(db_session) -> None:
    source = _seed_source(db_session)
    family = CourseWorkItemLabelFamily(
        user_id=source.user_id,
        course_dept="CSE",
        course_number=100,
        course_quarter="WI",
        course_year2=26,
        normalized_course_identity="cse:100::wi:26",
        canonical_label="Problem Set",
        normalized_canonical_label="problem set",
    )
    db_session.add(family)
    db_session.flush()
    due_at = datetime(2026, 3, 20, 18, 0, tzinfo=timezone.utc)
    db_session.add(
        EventEntity(
            user_id=source.user_id,
            entity_uid="ent-family-rename",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=100,
            course_quarter="WI",
            course_year2=26,
            family_id=family.id,
            raw_type="Homework",
            event_name="Homework 1",
            ordinal=1,
            due_date=due_at.date(),
            due_time=due_at.timetz().replace(tzinfo=None),
            time_precision="datetime",
        )
    )
    _add_observation(
        db_session,
        source=source,
        entity_uid="ent-family-rename",
        external_event_id="evt-family-rename",
        due_at=due_at,
        family_name="Problem Set",
        family_id=family.id,
        raw_type="Homework",
    )
    db_session.commit()

    created_count, pending_entity_uids = rebuild_pending_change_proposals(
        db=db_session,
        user_id=source.user_id,
        source=source,
        affected_entity_uids={"ent-family-rename"},
        applied_at=datetime.now(timezone.utc),
    )
    db_session.commit()

    assert created_count == 0
    assert pending_entity_uids == set()
    assert db_session.scalar(select(Change).where(Change.entity_uid == "ent-family-rename")) is None


def test_rebuild_removed_without_last_known_source_refs_fails_loudly(db_session) -> None:
    source = _seed_source(db_session)
    family = CourseWorkItemLabelFamily(
        user_id=source.user_id,
        course_dept="CSE",
        course_number=100,
        course_quarter="WI",
        course_year2=26,
        normalized_course_identity="cse:100::wi:26",
        canonical_label="Homework",
        normalized_canonical_label="homework",
    )
    db_session.add(family)
    db_session.flush()
    due_at = datetime(2026, 3, 20, 18, 0, tzinfo=timezone.utc)
    db_session.add(
        EventEntity(
            user_id=source.user_id,
            entity_uid="ent-missing-source-refs",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=100,
            course_quarter="WI",
            course_year2=26,
            family_id=family.id,
            raw_type="Homework",
            event_name="Homework 1",
            ordinal=1,
            due_date=due_at.date(),
            due_time=due_at.timetz().replace(tzinfo=None),
            time_precision="datetime",
        )
    )
    db_session.commit()

    created_count, pending_uids = rebuild_pending_change_proposals(
        db=db_session,
        user_id=source.user_id,
        source=source,
        affected_entity_uids={"ent-missing-source-refs"},
        applied_at=datetime.now(timezone.utc),
    )
    assert created_count == 0
    assert pending_uids == set()
    rejected_change = db_session.scalar(
        select(Change)
        .where(Change.user_id == source.user_id, Change.entity_uid == "ent-missing-source-refs")
        .order_by(Change.id.desc())
    )
    assert rejected_change is None or rejected_change.review_note in {None, "removed_proposal_missing_source_refs"}


def test_rebuild_preserves_manual_supported_entity_without_observations(db_session) -> None:
    source = _seed_source(db_session)
    family = CourseWorkItemLabelFamily(
        user_id=source.user_id,
        course_dept="CSE",
        course_number=100,
        course_quarter="WI",
        course_year2=26,
        normalized_course_identity="cse:100::wi:26",
        canonical_label="Homework",
        normalized_canonical_label="homework",
    )
    db_session.add(family)
    db_session.flush()
    due_at = datetime(2026, 3, 20, 18, 0, tzinfo=timezone.utc)
    db_session.add(
        EventEntity(
            user_id=source.user_id,
            entity_uid="ent-manual-supported",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=100,
            course_quarter="WI",
            course_year2=26,
            family_id=family.id,
            manual_support=True,
            raw_type="Homework",
            event_name="Homework 1",
            ordinal=1,
            due_date=due_at.date(),
            due_time=due_at.timetz().replace(tzinfo=None),
            time_precision="datetime",
        )
    )
    db_session.commit()

    created_count, pending_entity_uids = rebuild_pending_change_proposals(
        db=db_session,
        user_id=source.user_id,
        source=source,
        affected_entity_uids={"ent-manual-supported"},
        applied_at=datetime.now(timezone.utc),
    )
    db_session.commit()

    assert created_count == 0
    assert pending_entity_uids == set()
    assert db_session.scalar(select(Change).where(Change.entity_uid == "ent-manual-supported")) is None
