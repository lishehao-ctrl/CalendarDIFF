from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeType, Event, Input, InputType, ReviewStatus
from app.db.models.shared import User


def _create_user_and_input(db_session) -> tuple[User, Input]:
    user = User(
        email="batch-review@example.com",
        notify_email="batch-review@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    input_row = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key=f"canonical:user:{user.id}",
        is_active=True,
    )
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key=f"batch-source-{user.id}",
        display_name="Batch Source",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=datetime.now(timezone.utc),
    )
    db_session.add(input_row)
    db_session.add(source)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(input_row)
    return user, input_row


def _create_pending_change(db_session, *, input_id: int, event_uid: str, title: str, start_at: datetime) -> Change:
    row = Change(
        input_id=input_id,
        event_uid=event_uid,
        change_type=ChangeType.CREATED,
        detected_at=datetime.now(timezone.utc),
        before_json=None,
        after_json={
            "uid": event_uid,
            "title": title,
            "course_label": "CSE100",
            "start_at_utc": start_at.isoformat(),
            "end_at_utc": (start_at + timedelta(hours=1)).isoformat(),
        },
        delta_seconds=None,
        review_status=ReviewStatus.PENDING,
        proposal_merge_key=event_uid,
        proposal_sources_json=[],
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_review_changes_batch_approve_updates_multiple_pending_rows(client, db_session, auth_headers) -> None:
    user, input_row = _create_user_and_input(db_session)
    change_one = _create_pending_change(
        db_session,
        input_id=input_row.id,
        event_uid="batch-approve-1",
        title="Quiz 1",
        start_at=datetime(2026, 3, 10, 18, 0, tzinfo=timezone.utc),
    )
    change_two = _create_pending_change(
        db_session,
        input_id=input_row.id,
        event_uid="batch-approve-2",
        title="Quiz 2",
        start_at=datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc),
    )
    db_session.commit()

    headers = auth_headers(client, user=user)
    response = client.post(
        "/review/changes/batch/decisions",
        headers=headers,
        json={"ids": [change_one.id, change_two.id], "decision": "approve", "note": "batch approve"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "approve"
    assert payload["total_requested"] == 2
    assert payload["succeeded"] == 2
    assert payload["failed"] == 0
    assert all(item["ok"] is True for item in payload["results"])
    assert all(item["review_status"] == "approved" for item in payload["results"])

    db_session.expire_all()
    approved_rows = db_session.scalars(select(Change).where(Change.id.in_([change_one.id, change_two.id]))).all()
    assert all(row.review_status == ReviewStatus.APPROVED for row in approved_rows)
    events = db_session.scalars(select(Event).where(Event.input_id == input_row.id).order_by(Event.uid.asc())).all()
    assert [row.uid for row in events] == ["batch-approve-1", "batch-approve-2"]



def test_review_changes_batch_reject_reports_mixed_outcomes(client, db_session, auth_headers) -> None:
    user, input_row = _create_user_and_input(db_session)
    pending = _create_pending_change(
        db_session,
        input_id=input_row.id,
        event_uid="batch-reject-1",
        title="Homework",
        start_at=datetime(2026, 3, 14, 23, 59, tzinfo=timezone.utc),
    )
    reviewed = _create_pending_change(
        db_session,
        input_id=input_row.id,
        event_uid="batch-reject-2",
        title="Lab",
        start_at=datetime(2026, 3, 15, 23, 59, tzinfo=timezone.utc),
    )
    reviewed.review_status = ReviewStatus.APPROVED
    reviewed.reviewed_at = datetime.now(timezone.utc)
    reviewed.review_note = "already approved"
    db_session.commit()

    headers = auth_headers(client, user=user)
    response = client.post(
        "/review/changes/batch/decisions",
        headers=headers,
        json={"ids": [pending.id, reviewed.id, 999999], "decision": "reject", "note": "batch reject"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_requested"] == 3
    assert payload["succeeded"] == 2
    assert payload["failed"] == 1

    result_map = {row["id"]: row for row in payload["results"]}
    assert result_map[pending.id]["ok"] is True
    assert result_map[pending.id]["review_status"] == "rejected"
    assert result_map[reviewed.id]["ok"] is True
    assert result_map[reviewed.id]["idempotent"] is True
    assert result_map[999999]["ok"] is False
    assert result_map[999999]["error_code"] == "not_found"

    db_session.expire_all()
    refreshed_pending = db_session.get(Change, pending.id)
    refreshed_reviewed = db_session.get(Change, reviewed.id)
    assert refreshed_pending is not None and refreshed_pending.review_status == ReviewStatus.REJECTED
    assert refreshed_reviewed is not None and refreshed_reviewed.review_status == ReviewStatus.APPROVED
