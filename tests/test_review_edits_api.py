from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeType, Input, InputType, ReviewStatus
from app.db.models.shared import User


def _create_user_and_input(db_session, *, timezone_name: str = "UTC") -> tuple[User, Input]:
    user = User(
        email="review-edit@example.com",
        notify_email="review-edit@example.com",
        timezone_name=timezone_name,
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
        source_key=f"edit-source-{user.id}",
        display_name="Edit Source",
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


def test_review_edit_proposal_preview_and_apply_updates_pending_change(client, db_session, auth_headers) -> None:
    user, input_row = _create_user_and_input(db_session, timezone_name="America/Los_Angeles")
    start_at = datetime(2026, 3, 8, 7, 59, tzinfo=timezone.utc)
    change = Change(
        input_id=input_row.id,
        event_uid="proposal-edit-1",
        change_type=ChangeType.DUE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_json={
            "uid": "proposal-edit-1",
            "title": "HW1",
            "course_label": "CSE8A",
            "start_at_utc": start_at.isoformat(),
            "end_at_utc": (start_at + timedelta(hours=1)).isoformat(),
        },
        after_json={
            "uid": "proposal-edit-1",
            "title": "HW1",
            "course_label": "CSE8A",
            "start_at_utc": start_at.isoformat(),
            "end_at_utc": (start_at + timedelta(hours=1)).isoformat(),
        },
        delta_seconds=0,
        review_status=ReviewStatus.PENDING,
        proposal_merge_key="proposal-edit-1",
        proposal_sources_json=[],
    )
    db_session.add(change)
    db_session.commit()

    headers = auth_headers(client, user=user)
    preview_response = client.post(
        "/review/edits/preview",
        headers=headers,
        json={
            "mode": "proposal",
            "target": {"change_id": change.id},
            "patch": {"due_at": "2026-03-08", "title": "HW1 Updated", "course_label": "CSE8A"},
            "reason": "adjust proposal",
        },
    )
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["mode"] == "proposal"
    assert preview_payload["change_id"] == change.id
    assert preview_payload["candidate_after"]["title"] == "HW1 Updated"
    assert preview_payload["proposal_change_type"] == "due_changed"

    apply_response = client.post(
        "/review/edits",
        headers=headers,
        json={
            "mode": "proposal",
            "target": {"change_id": change.id},
            "patch": {"due_at": "2026-03-08", "title": "HW1 Updated", "course_label": "CSE8A"},
            "reason": "adjust proposal",
        },
    )
    assert apply_response.status_code == 200
    apply_payload = apply_response.json()
    assert apply_payload["mode"] == "proposal"
    assert apply_payload["edited_change_id"] == change.id

    db_session.expire_all()
    refreshed = db_session.get(Change, change.id)
    assert refreshed is not None
    assert refreshed.review_status == ReviewStatus.PENDING
    assert refreshed.after_json["title"] == "HW1 Updated"
    assert refreshed.after_snapshot_id is not None



def test_review_edit_proposal_rejects_removed_change(client, db_session, auth_headers) -> None:
    user, input_row = _create_user_and_input(db_session)
    change = Change(
        input_id=input_row.id,
        event_uid="proposal-removed-1",
        change_type=ChangeType.REMOVED,
        detected_at=datetime.now(timezone.utc),
        before_json={"uid": "proposal-removed-1"},
        after_json=None,
        delta_seconds=None,
        review_status=ReviewStatus.PENDING,
        proposal_merge_key="proposal-removed-1",
        proposal_sources_json=[],
    )
    db_session.add(change)
    db_session.commit()

    headers = auth_headers(client, user=user)
    response = client.post(
        "/review/edits/preview",
        headers=headers,
        json={
            "mode": "proposal",
            "target": {"change_id": change.id},
            "patch": {"due_at": "2026-03-08", "title": "Should fail", "course_label": "CSE8A"},
            "reason": "invalid",
        },
    )
    assert response.status_code == 409



def test_legacy_corrections_routes_are_removed(client, db_session, auth_headers) -> None:
    user, _ = _create_user_and_input(db_session)
    headers = auth_headers(client, user=user)
    preview_response = client.post(
        "/review/corrections/preview",
        headers=headers,
        json={
            "target": {"change_id": 1},
            "patch": {"due_at": "2026-03-08"},
            "reason": "legacy",
        },
    )
    apply_response = client.post(
        "/review/corrections",
        headers=headers,
        json={
            "target": {"change_id": 1},
            "patch": {"due_at": "2026-03-08"},
            "reason": "legacy",
        },
    )
    assert preview_response.status_code == 404
    assert apply_response.status_code == 404
