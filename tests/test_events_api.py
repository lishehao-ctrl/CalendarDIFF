from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import Event, Input, InputType
from app.modules.inputs.service import create_gmail_input_from_oauth


def test_events_requires_onboarded_user(client) -> None:
    headers = {"X-API-Key": "test-api-key"}
    response = client.get("/v1/events", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "user_not_initialized"


def test_events_lists_canonical_events_and_supports_filters(client, initialized_user, db_session) -> None:
    headers = {"X-API-Key": "test-api-key"}
    now = datetime.now(timezone.utc)

    ics_input = db_session.query(Input).filter(Input.user_id == initialized_user["id"], Input.type == InputType.ICS).one()
    email_input = create_gmail_input_from_oauth(
        db_session,
        user_id=initialized_user["id"],
        label="INBOX",
        from_contains=None,
        subject_keywords=None,
        account_email="mailbox@example.com",
        history_id=None,
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=now + timedelta(hours=1),
    ).input

    db_session.add_all(
        [
            Event(
                input_id=ics_input.id,
                uid="ics-event-1",
                course_label="CS101",
                title="Homework 1",
                start_at_utc=now + timedelta(days=1),
                end_at_utc=now + timedelta(days=1, hours=1),
            ),
            Event(
                input_id=email_input.id,
                uid="email-event-1",
                course_label="CS102",
                title="Project proposal due",
                start_at_utc=now + timedelta(days=2),
                end_at_utc=now + timedelta(days=2, hours=1),
            ),
        ]
    )
    db_session.commit()

    all_response = client.get("/v1/events?limit=50", headers=headers)
    assert all_response.status_code == 200
    all_rows = all_response.json()
    assert len(all_rows) == 2
    assert {row["input_type"] for row in all_rows} == {"ics", "email"}
    assert all("input_label" in row for row in all_rows)

    by_type = client.get("/v1/events?input_type=email", headers=headers)
    assert by_type.status_code == 200
    type_rows = by_type.json()
    assert len(type_rows) == 1
    assert type_rows[0]["input_type"] == "email"

    by_input = client.get(f"/v1/events?input_id={ics_input.id}", headers=headers)
    assert by_input.status_code == 200
    input_rows = by_input.json()
    assert len(input_rows) == 1
    assert input_rows[0]["input_id"] == ics_input.id

    by_query = client.get("/v1/events?q=proposal", headers=headers)
    assert by_query.status_code == 200
    query_rows = by_query.json()
    assert len(query_rows) == 1
    assert query_rows[0]["uid"] == "email-event-1"

