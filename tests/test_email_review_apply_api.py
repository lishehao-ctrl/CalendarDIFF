from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.db.models import Change, ChangeType, EmailActionItem, EmailMessage, EmailRoute, EmailRuleAnalysis, EmailRuleLabel, Event
from tests.helpers_inputs import create_ics_input_for_user


def _seed_apply_row(
    db_session,
    *,
    user_id: int,
    email_id: str,
    with_due: bool,
) -> None:
    message = EmailMessage(
        email_id=email_id,
        user_id=user_id,
        from_addr="instructor@school.edu",
        subject="[CSE 151A] assignment update",
        date_rfc822="2026-03-01T10:00:00-08:00",
        evidence_key={"kind": "email", "email_id": email_id},
    )
    label = EmailRuleLabel(
        email_id=email_id,
        label="KEEP",
        confidence=0.9,
        reasons=["action required"],
        course_hints=["CSE 151A"],
        event_type="assignment",
        raw_extract={
            "deadline_text": "2026-03-04T23:59:00-08:00" if with_due else None,
            "time_text": "2026-03-04T23:59:00-08:00" if with_due else None,
            "location_text": "Canvas",
        },
        notes=None,
    )
    if with_due:
        action = EmailActionItem(
            email_id=email_id,
            action="Submit assignment",
            due_iso="2026-03-04T23:59:00-08:00",
            where_text="Canvas",
        )
        db_session.add(action)
    analysis = EmailRuleAnalysis(
        email_id=email_id,
        event_flags={"assignment": True, "other": True},
        matched_snippets=[{"rule": "assignment", "snippet": "assignment update"}],
        drop_reason_codes=[],
    )
    route_row = EmailRoute(
        email_id=email_id,
        route="review",
        routed_at=datetime.now(timezone.utc),
        viewed_at=None,
        notified_at=None,
    )
    db_session.add_all([message, label, analysis, route_row])
    db_session.commit()


def test_apply_email_review_creates_event_and_change_on_earliest_active_ics(client, initialized_user, db_session) -> None:
    first_input_id = create_ics_input_for_user(
        db_session,
        user_id=initialized_user["id"],
        url="https://example.com/calendar-1.ics",
    )
    create_ics_input_for_user(
        db_session,
        user_id=initialized_user["id"],
        url="https://example.com/calendar-2.ics",
    )

    _seed_apply_row(db_session, user_id=1, email_id="email-apply-1", with_due=True)

    response = client.post(
        "/v1/emails/email-apply-1/apply",
        headers={"X-API-Key": "test-api-key"},
        json={},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] > 0
    assert payload["change_id"] > 0

    created_event = db_session.scalar(select(Event).where(Event.id == payload["task_id"]))
    assert created_event is not None
    assert created_event.input_id == first_input_id
    assert created_event.uid == "email-apply:email-apply-1"

    created_change = db_session.scalar(select(Change).where(Change.id == payload["change_id"]))
    assert created_change is not None
    assert created_change.change_type == ChangeType.CREATED

    route_row = db_session.get(EmailRoute, "email-apply-1")
    assert route_row is not None
    assert route_row.route == "archive"
    assert route_row.viewed_at is not None


def test_apply_email_review_without_due_returns_400_and_keeps_review_route(client, initialized_user, db_session) -> None:
    create_ics_input_for_user(
        db_session,
        user_id=initialized_user["id"],
        url="https://example.com/calendar-3.ics",
    )

    _seed_apply_row(db_session, user_id=1, email_id="email-apply-no-due", with_due=False)

    response = client.post(
        "/v1/emails/email-apply-no-due/apply",
        headers={"X-API-Key": "test-api-key"},
        json={},
    )
    assert response.status_code == 400
    assert "No parseable due/time" in response.json()["detail"]

    route_row = db_session.get(EmailRoute, "email-apply-no-due")
    assert route_row is not None
    assert route_row.route == "review"
    assert db_session.scalar(select(func.count(Event.id)).where(Event.uid == "email-apply:email-apply-no-due")) == 0
