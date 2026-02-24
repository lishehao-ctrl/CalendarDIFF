from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import (
    Change,
    ChangeType,
    EmailRuleCandidate,
    Event,
    Input,
    InputType,
    ReviewCandidateStatus,
    Snapshot,
    User,
)
from app.modules.inputs.service import create_gmail_input_from_oauth


def _create_pending_candidate(
    db_session,
    *,
    user_id: int,
    email_input_id: int,
    source_change_id: int | None,
    gmail_message_id: str = "m-candidate-1",
) -> EmailRuleCandidate:
    now = datetime.now(timezone.utc)
    candidate = EmailRuleCandidate(
        user_id=user_id,
        input_id=email_input_id,
        gmail_message_id=gmail_message_id,
        source_change_id=source_change_id,
        status=ReviewCandidateStatus.PENDING,
        rule_version="email-rules-v1",
        confidence=0.91,
        proposed_event_type="deadline",
        proposed_due_at=datetime(2026, 3, 2, 7, 59, tzinfo=timezone.utc),
        proposed_title="Homework due updated",
        proposed_course_hint="CSE 100",
        reasons=["actionable signal detected: deadline"],
        raw_extract={"deadline_text": "2026-03-01T23:59:00-08:00", "time_text": "2026-03-02T07:59:00+00:00", "location_text": None},
        subject="[CSE 100] homework deadline extension",
        from_header="instructor@school.edu",
        snippet="Homework deadline moved to Sunday 11:59 PM",
        applied_change_id=None,
        error=None,
        created_at=now,
        updated_at=now,
        applied_at=None,
        dismissed_at=None,
    )
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def test_review_candidates_list_and_gate(client, db_session) -> None:
    headers = {"X-API-Key": "test-api-key"}

    # Registered but not onboarded -> gate.
    create_user = client.post("/v1/user", headers=headers, json={"notify_email": "student@example.com"})
    assert create_user.status_code in {200, 201}
    gated = client.get("/v1/review_candidates", headers=headers)
    assert gated.status_code == 409
    assert gated.json()["detail"]["code"] == "user_onboarding_incomplete"

    user = db_session.scalar(select(User).order_by(User.id.asc()).limit(1))
    assert user is not None
    user.onboarding_completed_at = datetime.now(timezone.utc)
    db_session.commit()

    email_input = create_gmail_input_from_oauth(
        db_session,
        user_id=user.id,
        label=None,
        from_contains=None,
        subject_keywords=None,
        account_email="student@example.com",
        history_id="100",
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ).input
    _create_pending_candidate(db_session, user_id=user.id, email_input_id=email_input.id, source_change_id=None)

    ok = client.get("/v1/review_candidates", headers=headers)
    assert ok.status_code == 200
    rows = ok.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"


def test_apply_and_dismiss_review_candidate(client, initialized_user, db_session) -> None:
    headers = {"X-API-Key": "test-api-key"}
    user = db_session.scalar(select(User).order_by(User.id.asc()).limit(1))
    assert user is not None

    create_ics = client.post(
        "/v1/inputs/ics",
        headers=headers,
        json={"url": "https://example.com/calendar.ics"},
    )
    assert create_ics.status_code == 201
    ics_input_id = create_ics.json()["id"]
    ics_input = db_session.get(Input, ics_input_id)
    assert ics_input is not None

    event = Event(
        input_id=ics_input.id,
        uid="evt-1",
        course_label="CSE 100",
        title="HW 1",
        start_at_utc=datetime(2026, 3, 1, 7, 59, tzinfo=timezone.utc),
        end_at_utc=datetime(2026, 3, 1, 8, 59, tzinfo=timezone.utc),
    )
    db_session.add(event)
    baseline_snapshot = Snapshot(
        input_id=ics_input.id,
        retrieved_at=datetime.now(timezone.utc),
        etag="v1",
        content_hash="snapshot-v1",
        event_count=1,
        raw_evidence_key={"kind": "ics"},
    )
    db_session.add(baseline_snapshot)

    email_input = create_gmail_input_from_oauth(
        db_session,
        user_id=user.id,
        label=None,
        from_contains=None,
        subject_keywords=None,
        account_email="student@example.com",
        history_id="100",
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ).input
    source_snapshot = Snapshot(
        input_id=email_input.id,
        retrieved_at=datetime.now(timezone.utc),
        etag=None,
        content_hash="email-snapshot-v1",
        event_count=1,
        raw_evidence_key={"kind": "gmail"},
    )
    db_session.add(source_snapshot)
    db_session.flush()
    source_change = Change(
        input_id=email_input.id,
        user_term_id=None,
        event_uid="m-candidate-1",
        change_type=ChangeType.CREATED,
        detected_at=datetime.now(timezone.utc),
        before_json=None,
        after_json={"subject": "s"},
        delta_seconds=None,
        before_snapshot_id=None,
        after_snapshot_id=source_snapshot.id,
        evidence_keys={"after": {"kind": "gmail"}},
    )
    db_session.add(source_change)
    db_session.commit()
    db_session.refresh(source_change)

    candidate = _create_pending_candidate(
        db_session,
        user_id=user.id,
        email_input_id=email_input.id,
        source_change_id=source_change.id,
    )

    apply_response = client.post(
        f"/v1/review_candidates/{candidate.id}/apply",
        headers=headers,
        json={
            "target_input_id": ics_input.id,
            "target_event_uid": "evt-1",
        },
    )
    assert apply_response.status_code == 200
    apply_payload = apply_response.json()
    assert apply_payload["candidate"]["status"] == "applied"
    assert apply_payload["applied_change_id"] > 0

    db_session.expire_all()
    refreshed_event = db_session.scalar(select(Event).where(Event.id == event.id))
    assert refreshed_event is not None
    assert refreshed_event.start_at_utc.isoformat() == "2026-03-02T07:59:00+00:00"

    due_change = db_session.scalar(
        select(Change).where(
            Change.input_id == ics_input.id,
            Change.change_type == ChangeType.DUE_CHANGED,
        )
    )
    assert due_change is not None

    # Create another pending candidate and dismiss it.
    candidate_to_dismiss = _create_pending_candidate(
        db_session,
        user_id=user.id,
        email_input_id=email_input.id,
        source_change_id=source_change.id,
        gmail_message_id="m-candidate-2",
    )
    dismiss_response = client.post(
        f"/v1/review_candidates/{candidate_to_dismiss.id}/dismiss",
        headers=headers,
        json={"note": "not relevant"},
    )
    assert dismiss_response.status_code == 200
    assert dismiss_response.json()["candidate"]["status"] == "dismissed"
