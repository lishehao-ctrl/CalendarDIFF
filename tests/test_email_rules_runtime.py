from __future__ import annotations

from app.modules.sync.email_rules import evaluate_email_rule


def test_evaluate_email_rule_parses_iso_due_datetime() -> None:
    decision = evaluate_email_rule(
        subject="[CSE 100] deadline moved",
        snippet="",
        body_text="The new due time is 2026-03-01T23:59:00-08:00.",
        from_header="instructor@school.edu",
        internal_date="2026-02-20T10:00:00+00:00",
        timezone_name="America/Los_Angeles",
    )
    assert decision.event_type == "schedule_change"
    assert decision.score == 1.0
    assert decision.decision_origin == "rule"
    assert decision.due_at is not None
    assert decision.due_at.isoformat() == "2026-03-02T07:59:00+00:00"
    assert decision.raw_extract["deadline_text"] == "2026-03-01T23:59:00-08:00"


def test_evaluate_email_rule_parses_month_day_with_internal_date_year_fallback() -> None:
    decision = evaluate_email_rule(
        subject="[CSE 100] assignment update",
        snippet="",
        body_text="Homework due Mar 3 11:59 PM PT.",
        from_header="instructor@school.edu",
        internal_date="2027-02-10T10:00:00+00:00",
        timezone_name="America/Los_Angeles",
    )
    assert decision.event_type == "deadline"
    assert decision.score == 1.0
    assert decision.due_at is not None
    assert decision.due_at.isoformat() == "2027-03-04T07:59:00+00:00"
    assert decision.raw_extract["deadline_text"] == "Mar 3 11:59 PM PT"


def test_evaluate_email_rule_parses_mdy_and_prefers_tz_abbreviation() -> None:
    decision = evaluate_email_rule(
        subject="[CSE 100] deadline extension",
        snippet="",
        body_text="Submission due 3/3/2026 11:59 PM ET.",
        from_header="instructor@school.edu",
        internal_date="2026-02-10T10:00:00+00:00",
        timezone_name="America/Los_Angeles",
    )
    assert decision.event_type == "deadline"
    assert decision.score == 1.0
    assert decision.due_at is not None
    assert decision.due_at.isoformat() == "2026-03-04T04:59:00+00:00"
    assert decision.raw_extract["deadline_text"] == "3/3/2026 11:59 PM ET"


def test_evaluate_email_rule_preserves_event_priority() -> None:
    decision = evaluate_email_rule(
        subject="[CSE 100] schedule moved and deadline extended",
        snippet="Class moved and deadline moved",
        body_text="See details in announcement.",
        from_header="instructor@school.edu",
        internal_date="2026-02-10T10:00:00+00:00",
    )
    assert decision.event_type == "schedule_change"
    assert decision.score == 0.0


def test_evaluate_email_rule_returns_none_due_when_no_date_detected() -> None:
    decision = evaluate_email_rule(
        subject="[CSE 100] assignment reminder",
        snippet="Please submit soon",
        body_text="No explicit date in this email",
        from_header="instructor@school.edu",
        internal_date="2026-02-10T10:00:00+00:00",
    )
    assert decision.event_type == "assignment"
    assert decision.score == 0.0
    assert decision.due_at is None
    assert decision.raw_extract["deadline_text"] is None
    assert decision.raw_extract["time_text"] is None


def test_evaluate_email_rule_assigns_negative_score_for_strong_non_actionable() -> None:
    decision = evaluate_email_rule(
        subject="Weekly campus bulletin",
        snippet="Community updates",
        body_text="Welcome to this week's campus newsletter",
        from_header="news@school.edu",
        internal_date="2026-02-10T10:00:00+00:00",
    )
    assert decision.label == "DROP"
    assert decision.event_type is None
    assert decision.score == -1.0
