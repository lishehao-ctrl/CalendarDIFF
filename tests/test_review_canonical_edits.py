from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeType, Event, Input, InputType, ReviewStatus
from app.db.models.shared import IntegrationOutbox, User


def _headers(client, auth_headers, user) -> dict[str, str]:
    return auth_headers(client, user=user)


def _as_utc(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _create_onboarded_user(db_session, *, timezone_name: str = "UTC") -> User:
    now = datetime.now(timezone.utc)
    user = User(
        email="canonical-edit@example.com",
        notify_email="canonical-edit@example.com",
        timezone_name=timezone_name,
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key=f"canonical-edit-source-{user.id}",
        display_name="Canonical Edit Source",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_canonical_input(db_session, *, user_id: int) -> Input:
    row = Input(
        user_id=user_id,
        type=InputType.ICS,
        identity_key=f"canonical:user:{user_id}",
        is_active=True,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_canonical_edit_preview_uses_date_only_as_local_2359(client, db_session, auth_headers) -> None:
    user = _create_onboarded_user(db_session, timezone_name="America/Los_Angeles")
    canonical_input = _create_canonical_input(db_session, user_id=user.id)
    event_uid = "cse8a-hw1-deadline"

    existing_start = datetime(2026, 3, 1, 7, 59, tzinfo=timezone.utc)
    db_session.add(
        Event(
            input_id=canonical_input.id,
            uid=event_uid,
            course_label="CSE8A",
            title="CSE8A HW1 Deadline",
            start_at_utc=existing_start,
            end_at_utc=existing_start + timedelta(hours=1),
        )
    )
    target_change = Change(
        input_id=canonical_input.id,
        event_uid=event_uid,
        change_type=ChangeType.DUE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_json=None,
        after_json={
            "uid": event_uid,
            "title": "CSE8A HW1 Deadline",
            "course_label": "CSE8A",
            "start_at_utc": existing_start.isoformat(),
            "end_at_utc": (existing_start + timedelta(hours=1)).isoformat(),
        },
        delta_seconds=None,
        review_status=ReviewStatus.PENDING,
        proposal_merge_key=event_uid,
        proposal_sources_json=[],
    )
    extra_pending = Change(
        input_id=canonical_input.id,
        event_uid=event_uid,
        change_type=ChangeType.DUE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_json=None,
        after_json={
            "uid": event_uid,
            "title": "CSE8A HW1 Deadline",
            "course_label": "CSE8A",
            "start_at_utc": existing_start.isoformat(),
            "end_at_utc": (existing_start + timedelta(hours=1)).isoformat(),
        },
        delta_seconds=None,
        review_status=ReviewStatus.PENDING,
        proposal_merge_key=event_uid,
        proposal_sources_json=[],
    )
    db_session.add_all([target_change, extra_pending])
    db_session.commit()

    response = client.post(
        "/review/edits/preview",
        headers=_headers(client, auth_headers, user),
        json={
            "mode": "canonical",
            "target": {"change_id": target_change.id, "event_uid": None},
            "patch": {
                "due_at": "2026-03-01",
                "title": "HW1 Deadline (Corrected)",
                "course_label": "CSE8A",
            },
            "reason": "syllabus says 11:59 PM",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["event_uid"] == event_uid
    assert _as_utc(payload["candidate_after"]["start_at_utc"]) == datetime(2026, 3, 2, 7, 59, tzinfo=timezone.utc)
    assert _as_utc(payload["candidate_after"]["end_at_utc"]) == datetime(2026, 3, 2, 8, 59, tzinfo=timezone.utc)
    assert payload["delta_seconds"] == 86400
    assert payload["idempotent"] is False
    assert payload["will_reject_pending_change_ids"] == sorted([target_change.id, extra_pending.id])


def test_canonical_edit_apply_updates_canonical_and_rejects_pending(client, db_session, auth_headers) -> None:
    user = _create_onboarded_user(db_session, timezone_name="UTC")
    canonical_input = _create_canonical_input(db_session, user_id=user.id)
    event_uid = "math20b-hw2-deadline"
    current_start = datetime(2026, 3, 3, 23, 59, tzinfo=timezone.utc)
    existing_event = Event(
        input_id=canonical_input.id,
        uid=event_uid,
        course_label="MATH20B",
        title="HW2 Deadline",
        start_at_utc=current_start,
        end_at_utc=current_start + timedelta(hours=1),
    )
    pending = Change(
        input_id=canonical_input.id,
        event_uid=event_uid,
        change_type=ChangeType.DUE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_json=None,
        after_json={
            "uid": event_uid,
            "title": "HW2 Deadline",
            "course_label": "MATH20B",
            "start_at_utc": current_start.isoformat(),
            "end_at_utc": (current_start + timedelta(hours=1)).isoformat(),
        },
        delta_seconds=None,
        review_status=ReviewStatus.PENDING,
        proposal_merge_key=event_uid,
        proposal_sources_json=[],
    )
    db_session.add_all([existing_event, pending])
    db_session.commit()

    response = client.post(
        "/review/edits",
        headers=_headers(client, auth_headers, user),
        json={
            "mode": "canonical",
            "target": {"change_id": None, "event_uid": event_uid},
            "patch": {
                "due_at": "2026-03-05T23:59:00Z",
                "title": "HW2 Deadline (Corrected)",
                "course_label": "MATH20B",
            },
            "reason": "course site update",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["applied"] is True
    assert payload["idempotent"] is False
    assert isinstance(payload["canonical_edit_change_id"], int)
    assert payload["rejected_pending_change_ids"] == [pending.id]

    db_session.expire_all()
    refreshed_event = db_session.scalar(
        select(Event).where(Event.input_id == canonical_input.id, Event.uid == event_uid)
    )
    assert refreshed_event is not None
    assert refreshed_event.start_at_utc.isoformat() == "2026-03-05T23:59:00+00:00"
    assert refreshed_event.title == "HW2 Deadline (Corrected)"

    refreshed_pending = db_session.get(Change, pending.id)
    assert refreshed_pending is not None
    assert refreshed_pending.review_status == ReviewStatus.REJECTED
    assert refreshed_pending.review_note == f"superseded_by_canonical_edit:{payload['canonical_edit_change_id']}"

    canonical_edit_row = db_session.get(Change, payload["canonical_edit_change_id"])
    assert canonical_edit_row is not None
    assert canonical_edit_row.review_status == ReviewStatus.APPROVED
    assert canonical_edit_row.change_type == ChangeType.DUE_CHANGED
    assert canonical_edit_row.review_note == "canonical_edit:course site update"

    outbox_row = db_session.scalar(
        select(IntegrationOutbox)
        .where(
            IntegrationOutbox.event_type == "review.decision.approved",
            IntegrationOutbox.aggregate_id == str(payload["canonical_edit_change_id"]),
        )
        .order_by(IntegrationOutbox.id.desc())
        .limit(1)
    )
    assert outbox_row is not None
    assert isinstance(outbox_row.payload_json, dict)
    assert outbox_row.payload_json.get("decision_origin") == "canonical_edit"


def test_canonical_edit_apply_can_create_canonical_event_from_pending(client, db_session, auth_headers) -> None:
    user = _create_onboarded_user(db_session, timezone_name="UTC")
    canonical_input = _create_canonical_input(db_session, user_id=user.id)
    event_uid = "cse100-hw3-deadline"
    pending_due = "2026-03-09T23:59:00+00:00"
    db_session.add(
        Change(
            input_id=canonical_input.id,
            event_uid=event_uid,
            change_type=ChangeType.CREATED,
            detected_at=datetime.now(timezone.utc),
            before_json=None,
            after_json={
                "uid": event_uid,
                "title": "HW3 Deadline",
                "course_label": "CSE100",
                "start_at_utc": pending_due,
                "end_at_utc": "2026-03-10T00:59:00+00:00",
            },
            delta_seconds=None,
            review_status=ReviewStatus.PENDING,
            proposal_merge_key=event_uid,
            proposal_sources_json=[],
        )
    )
    db_session.commit()

    response = client.post(
        "/review/edits",
        headers=_headers(client, auth_headers, user),
        json={
            "mode": "canonical",
            "target": {"change_id": None, "event_uid": event_uid},
            "patch": {
                "due_at": "2026-03-10",
                "title": "HW3 Deadline (Manual)",
                "course_label": "CSE100",
            },
            "reason": "manual fix",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["idempotent"] is False

    event_row = db_session.scalar(
        select(Event).where(Event.input_id == canonical_input.id, Event.uid == event_uid)
    )
    assert event_row is not None
    assert event_row.title == "HW3 Deadline (Manual)"
    assert event_row.start_at_utc.isoformat() == "2026-03-10T23:59:00+00:00"

    canonical_edit_row = db_session.get(Change, payload["canonical_edit_change_id"])
    assert canonical_edit_row is not None
    assert canonical_edit_row.change_type == ChangeType.CREATED
    assert canonical_edit_row.review_status == ReviewStatus.APPROVED


def test_canonical_edit_apply_idempotent_when_candidate_matches_canonical(client, db_session, auth_headers) -> None:
    user = _create_onboarded_user(db_session, timezone_name="UTC")
    canonical_input = _create_canonical_input(db_session, user_id=user.id)
    event_uid = "ece45-hw4-deadline"
    due_at = datetime(2026, 3, 12, 23, 59, tzinfo=timezone.utc)
    db_session.add(
        Event(
            input_id=canonical_input.id,
            uid=event_uid,
            course_label="ECE45",
            title="HW4 Deadline",
            start_at_utc=due_at,
            end_at_utc=due_at + timedelta(hours=1),
        )
    )
    db_session.commit()

    before_count = db_session.scalar(select(func.count(Change.id))) or 0
    response = client.post(
        "/review/edits",
        headers=_headers(client, auth_headers, user),
        json={
            "mode": "canonical",
            "target": {"change_id": None, "event_uid": event_uid},
            "patch": {
                "due_at": "2026-03-12T23:59:00Z",
                "title": "HW4 Deadline",
                "course_label": "ECE45",
            },
            "reason": "same value",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["idempotent"] is True
    assert payload["canonical_edit_change_id"] is None
    assert payload["rejected_pending_change_ids"] == []
    after_count = db_session.scalar(select(func.count(Change.id))) or 0
    assert after_count == before_count


def test_canonical_edit_rejects_mismatched_target(client, db_session, auth_headers) -> None:
    user = _create_onboarded_user(db_session, timezone_name="UTC")
    canonical_input = _create_canonical_input(db_session, user_id=user.id)
    event_uid = "cse11-hw5-deadline"
    due_at = datetime(2026, 3, 15, 23, 59, tzinfo=timezone.utc)
    change = Change(
        input_id=canonical_input.id,
        event_uid=event_uid,
        change_type=ChangeType.DUE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_json=None,
        after_json={
            "uid": event_uid,
            "title": "HW5 Deadline",
            "course_label": "CSE11",
            "start_at_utc": due_at.isoformat(),
            "end_at_utc": (due_at + timedelta(hours=1)).isoformat(),
        },
        delta_seconds=None,
        review_status=ReviewStatus.PENDING,
        proposal_merge_key=event_uid,
        proposal_sources_json=[],
    )
    db_session.add(change)
    db_session.commit()

    response = client.post(
        "/review/edits/preview",
        headers=_headers(client, auth_headers, user),
        json={
            "mode": "canonical",
            "target": {"change_id": change.id, "event_uid": "mismatch-uid"},
            "patch": {"due_at": "2026-03-15", "title": "HW5", "course_label": "CSE11"},
            "reason": "target mismatch",
        },
    )
    assert response.status_code == 422
    assert "must reference the same event_uid" in str(response.json()["detail"])
