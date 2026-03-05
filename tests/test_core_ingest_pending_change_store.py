from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db.models.review import Change, ChangeType, Input, InputType, ReviewStatus, Snapshot
from app.db.models.shared import User
from app.modules.core_ingest.pending_change_store import (
    resolve_pending_change_as_rejected,
    upsert_pending_change,
)


def _seed_canonical_input(db_session) -> Input:
    user = User(email="pending-store@example.com", notify_email="pending-store@example.com")
    db_session.add(user)
    db_session.flush()
    input_row = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key=f"canonical:user:{user.id}",
        is_active=True,
    )
    db_session.add(input_row)
    db_session.commit()
    db_session.refresh(input_row)
    return input_row


def test_upsert_pending_change_creates_new_row(db_session) -> None:
    input_row = _seed_canonical_input(db_session)
    detected_at = datetime.now(timezone.utc)
    created = upsert_pending_change(
        db=db_session,
        input_id=input_row.id,
        event_uid="evt-create",
        change_type=ChangeType.CREATED,
        before_json=None,
        after_json={"uid": "evt-create", "title": "Homework", "start_at_utc": "2026-03-01T10:00:00+00:00", "end_at_utc": "2026-03-01T11:00:00+00:00"},
        delta_seconds=None,
        proposal_merge_key="evt-create",
        proposal_sources_json=[{"source_kind": "calendar"}],
        detected_at=detected_at,
    )
    assert created is not None
    assert created.review_status == ReviewStatus.PENDING
    assert created.proposal_merge_key == "evt-create"

    count = db_session.scalar(select(func.count(Change.id)).where(Change.input_id == input_row.id))
    assert int(count or 0) == 1


def test_upsert_pending_change_returns_none_when_payload_is_unchanged(db_session) -> None:
    input_row = _seed_canonical_input(db_session)
    detected_at = datetime.now(timezone.utc)
    _ = upsert_pending_change(
        db=db_session,
        input_id=input_row.id,
        event_uid="evt-same",
        change_type=ChangeType.DUE_CHANGED,
        before_json={"uid": "evt-same", "start_at_utc": "2026-03-01T10:00:00+00:00"},
        after_json={"uid": "evt-same", "start_at_utc": "2026-03-01T12:00:00+00:00"},
        delta_seconds=7200,
        proposal_merge_key="evt-same",
        proposal_sources_json=[{"source_kind": "calendar"}],
        detected_at=detected_at,
    )
    second = upsert_pending_change(
        db=db_session,
        input_id=input_row.id,
        event_uid="evt-same",
        change_type=ChangeType.DUE_CHANGED,
        before_json={"uid": "evt-same", "start_at_utc": "2026-03-01T10:00:00+00:00"},
        after_json={"uid": "evt-same", "start_at_utc": "2026-03-01T12:00:00+00:00"},
        delta_seconds=7200,
        proposal_merge_key="evt-same",
        proposal_sources_json=[{"source_kind": "calendar"}],
        detected_at=detected_at + timedelta(minutes=5),
    )
    assert second is None

    count = db_session.scalar(
        select(func.count(Change.id)).where(
            Change.input_id == input_row.id,
            Change.event_uid == "evt-same",
        )
    )
    assert int(count or 0) == 1


def test_upsert_pending_change_updates_existing_pending_and_resets_review_fields(db_session) -> None:
    input_row = _seed_canonical_input(db_session)
    original_detected_at = datetime.now(timezone.utc)
    updated_detected_at = original_detected_at + timedelta(minutes=10)

    created = upsert_pending_change(
        db=db_session,
        input_id=input_row.id,
        event_uid="evt-update",
        change_type=ChangeType.CREATED,
        before_json=None,
        after_json={"uid": "evt-update", "start_at_utc": "2026-03-01T10:00:00+00:00"},
        delta_seconds=None,
        proposal_merge_key="evt-update",
        proposal_sources_json=[{"source_kind": "calendar"}],
        detected_at=original_detected_at,
    )
    assert created is not None
    before_snapshot = Snapshot(
        input_id=input_row.id,
        content_hash="b" * 64,
        event_count=1,
        raw_evidence_key=None,
    )
    after_snapshot = Snapshot(
        input_id=input_row.id,
        content_hash="a" * 64,
        event_count=1,
        raw_evidence_key=None,
    )
    db_session.add_all([before_snapshot, after_snapshot])
    db_session.flush()
    created.viewed_at = original_detected_at
    created.viewed_note = "viewed"
    created.reviewed_at = original_detected_at
    created.review_note = "old note"
    created.reviewed_by_user_id = input_row.user_id
    created.before_snapshot_id = before_snapshot.id
    created.after_snapshot_id = after_snapshot.id
    created.evidence_keys = {"a": 1}
    db_session.commit()

    result = upsert_pending_change(
        db=db_session,
        input_id=input_row.id,
        event_uid="evt-update",
        change_type=ChangeType.DUE_CHANGED,
        before_json={"uid": "evt-update", "start_at_utc": "2026-03-01T10:00:00+00:00"},
        after_json={"uid": "evt-update", "start_at_utc": "2026-03-01T14:00:00+00:00"},
        delta_seconds=14400,
        proposal_merge_key="evt-update",
        proposal_sources_json=[{"source_kind": "email"}],
        detected_at=updated_detected_at,
    )
    assert result is None
    db_session.commit()

    refreshed = db_session.scalar(
        select(Change).where(
            Change.input_id == input_row.id,
            Change.event_uid == "evt-update",
            Change.review_status == ReviewStatus.PENDING,
        )
    )
    assert refreshed is not None
    assert refreshed.change_type == ChangeType.DUE_CHANGED
    assert refreshed.detected_at == updated_detected_at
    assert refreshed.viewed_at is None
    assert refreshed.viewed_note is None
    assert refreshed.reviewed_at is None
    assert refreshed.review_note is None
    assert refreshed.reviewed_by_user_id is None
    assert refreshed.proposal_sources_json == [{"source_kind": "email"}]
    assert refreshed.before_snapshot_id is None
    assert refreshed.after_snapshot_id is None
    assert refreshed.evidence_keys is None


def test_resolve_pending_change_as_rejected_only_changes_pending_rows(db_session) -> None:
    input_row = _seed_canonical_input(db_session)
    detected_at = datetime.now(timezone.utc)

    first = upsert_pending_change(
        db=db_session,
        input_id=input_row.id,
        event_uid="evt-reject",
        change_type=ChangeType.CREATED,
        before_json=None,
        after_json={"uid": "evt-reject"},
        delta_seconds=None,
        proposal_merge_key="evt-reject",
        proposal_sources_json=[],
        detected_at=detected_at,
    )
    second = upsert_pending_change(
        db=db_session,
        input_id=input_row.id,
        event_uid="evt-reject",
        change_type=ChangeType.DUE_CHANGED,
        before_json={"uid": "evt-reject"},
        after_json={"uid": "evt-reject", "title": "updated"},
        delta_seconds=300,
        proposal_merge_key="evt-reject",
        proposal_sources_json=[],
        detected_at=detected_at + timedelta(minutes=1),
    )
    assert first is not None
    assert second is None

    untouched = Change(
        input_id=input_row.id,
        event_uid="evt-other",
        change_type=ChangeType.CREATED,
        detected_at=detected_at,
        before_json=None,
        after_json={"uid": "evt-other"},
        delta_seconds=None,
        review_status=ReviewStatus.PENDING,
        reviewed_at=None,
        review_note=None,
        reviewed_by_user_id=None,
        proposal_merge_key="evt-other",
        proposal_sources_json=[],
    )
    db_session.add(untouched)
    db_session.commit()

    reviewed_at = detected_at + timedelta(minutes=2)
    resolve_pending_change_as_rejected(
        db=db_session,
        canonical_input_id=input_row.id,
        event_uid="evt-reject",
        applied_at=reviewed_at,
        note="proposal_resolved_no_active_observation",
    )
    db_session.commit()

    rejected_rows = db_session.scalars(
        select(Change).where(
            Change.input_id == input_row.id,
            Change.event_uid == "evt-reject",
        )
    ).all()
    assert rejected_rows
    assert all(row.review_status == ReviewStatus.REJECTED for row in rejected_rows)
    assert all(row.review_note == "proposal_resolved_no_active_observation" for row in rejected_rows)
    assert all(row.reviewed_at == reviewed_at for row in rejected_rows)

    untouched_row = db_session.scalar(select(Change).where(Change.id == untouched.id))
    assert untouched_row is not None
    assert untouched_row.review_status == ReviewStatus.PENDING
