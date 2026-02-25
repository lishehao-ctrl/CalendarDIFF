from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import ChangeType, Snapshot, SnapshotEvent, Input, InputType, User
from app.modules.diff.engine import EventState, compute_diff
from app.modules.sync.service import _find_debounced_removed_uids
from app.modules.sync.types import CanonicalEventInput


def _dt(hour: int) -> datetime:
    return datetime(2026, 2, 20, hour, 0, tzinfo=timezone.utc)


def test_diff_detects_created_event() -> None:
    canonical = {}
    snapshot = {
        "uid-1": CanonicalEventInput(
            uid="uid-1",
            course_label="CSE 151A",
            title="HW",
            start_at_utc=_dt(10),
            end_at_utc=_dt(11),
        )
    }

    result = compute_diff(canonical_events=canonical, snapshot_events=snapshot, debounced_removed_uids=set())

    assert len(result.created_events) == 1
    assert len(result.changes) == 1
    assert result.changes[0].change_type == ChangeType.CREATED


def test_diff_priority_due_over_title_and_course() -> None:
    canonical = {
        "uid-1": EventState(
            uid="uid-1",
            course_label="CSE 151A",
            title="Old title",
            start_at_utc=_dt(10),
            end_at_utc=_dt(11),
        )
    }
    snapshot = {
        "uid-1": CanonicalEventInput(
            uid="uid-1",
            course_label="MATH 20A",
            title="New title",
            start_at_utc=_dt(12),
            end_at_utc=_dt(13),
        )
    }

    result = compute_diff(canonical_events=canonical, snapshot_events=snapshot, debounced_removed_uids=set())

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.change_type == ChangeType.DUE_CHANGED
    assert change.delta_seconds == 7200
    assert set(change.before_json or {}) == {"course_label", "end_at_utc", "start_at_utc", "title"}
    assert set(change.after_json or {}) == {"course_label", "end_at_utc", "start_at_utc", "title"}


def test_diff_noop_when_event_unchanged() -> None:
    canonical = {
        "uid-1": EventState(
            uid="uid-1",
            course_label="CSE 151A",
            title="Same",
            start_at_utc=_dt(10),
            end_at_utc=_dt(11),
        )
    }
    snapshot = {
        "uid-1": CanonicalEventInput(
            uid="uid-1",
            course_label="CSE 151A",
            title="Same",
            start_at_utc=_dt(10),
            end_at_utc=_dt(11),
        )
    }

    result = compute_diff(canonical_events=canonical, snapshot_events=snapshot, debounced_removed_uids=set())

    assert result.changes == []
    assert result.updated_events == []


def test_removed_requires_three_consecutive_missing_snapshots(db_session: Session) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key="Test",
        encrypted_url="encrypted",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.flush()

    snap1 = Snapshot(input_id=source.id, content_hash="a", event_count=0)
    snap2 = Snapshot(input_id=source.id, content_hash="b", event_count=0)
    db_session.add_all([snap1, snap2])
    db_session.flush()

    # only two snapshots so far, candidate removal must not pass debounce
    candidate = {"uid-removed"}
    debounced = _find_debounced_removed_uids(db_session, input_id=source.id, candidate_uids=candidate)
    assert debounced == set()

    snap3 = Snapshot(input_id=source.id, content_hash="c", event_count=0)
    db_session.add(snap3)
    db_session.flush()

    # still absent in all latest 3 snapshots -> removal is now allowed
    debounced = _find_debounced_removed_uids(db_session, input_id=source.id, candidate_uids=candidate)
    assert debounced == {"uid-removed"}

    # if event appears in one of latest three snapshots, debounce blocks removal
    db_session.add(
        SnapshotEvent(
            snapshot_id=snap3.id,
            uid="uid-removed",
            course_label="Unknown",
            title="Back",
            start_at_utc=_dt(8),
            end_at_utc=_dt(9),
        )
    )
    db_session.flush()

    debounced = _find_debounced_removed_uids(db_session, input_id=source.id, candidate_uids=candidate)
    assert debounced == set()
