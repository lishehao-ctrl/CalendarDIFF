from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import (
    EmailActionItem,
    EmailMessage,
    EmailRoute,
    EmailRuleAnalysis,
    EmailRuleLabel,
)


def _seed_email_queue_row(db_session, *, user_id: int, email_id: str = "email-review-1", route: str = "review") -> None:
    message = EmailMessage(
        email_id=email_id,
        user_id=user_id,
        from_addr="instructor@school.edu",
        subject="[CSE 100] deadline moved",
        date_rfc822="2026-03-01T10:00:00-08:00",
        evidence_key={"kind": "email", "email_id": email_id},
    )
    label = EmailRuleLabel(
        email_id=email_id,
        label="KEEP",
        confidence=0.91,
        reasons=["deadline signal"],
        course_hints=["CSE 100"],
        event_type="deadline",
        raw_extract={"deadline_text": "2026-03-03T23:59:00-08:00", "time_text": "2026-03-03T23:59:00-08:00", "location_text": "Gradescope"},
        notes=None,
    )
    action = EmailActionItem(
        email_id=email_id,
        action="Submit homework",
        due_iso="2026-03-03T23:59:00-08:00",
        where_text="Gradescope",
    )
    analysis = EmailRuleAnalysis(
        email_id=email_id,
        event_flags={"deadline": True, "schedule_change": False, "other": True},
        matched_snippets=[{"rule": "deadline", "snippet": "deadline moved"}],
        drop_reason_codes=[],
    )
    route_row = EmailRoute(
        email_id=email_id,
        route=route,
        routed_at=datetime.now(timezone.utc),
        viewed_at=None,
        notified_at=None,
    )
    db_session.add_all([message, label, action, analysis, route_row])
    db_session.commit()


def test_email_queue_returns_expected_shape_without_body(client, initialized_user, db_session) -> None:
    _seed_email_queue_row(db_session, user_id=1)

    response = client.get("/v1/emails/queue?route=review", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["email_id"] == "email-review-1"
    assert row["subject"] == "[CSE 100] deadline moved"
    assert row["event_type"] == "deadline"
    assert row["action_items"][0]["due_iso"] == "2026-03-03T23:59:00-08:00"
    assert row["rule_analysis"]["matched_snippets"][0]["rule"] == "deadline"
    assert row["flags"]["viewed"] is False
    assert "body_text" not in row


def test_email_route_archive_drop_and_mark_viewed(client, initialized_user, db_session) -> None:
    _seed_email_queue_row(db_session, user_id=1)

    to_archive = client.post(
        "/v1/emails/email-review-1/route",
        headers={"X-API-Key": "test-api-key"},
        json={"route": "archive"},
    )
    assert to_archive.status_code == 200
    assert to_archive.json()["route"] == "archive"

    to_drop = client.post(
        "/v1/emails/email-review-1/route",
        headers={"X-API-Key": "test-api-key"},
        json={"route": "drop"},
    )
    assert to_drop.status_code == 200
    assert to_drop.json()["route"] == "drop"

    viewed = client.post("/v1/emails/email-review-1/mark_viewed", headers={"X-API-Key": "test-api-key"})
    assert viewed.status_code == 200
    route_row = db_session.get(EmailRoute, "email-review-1")
    assert route_row is not None
    assert route_row.viewed_at is not None
