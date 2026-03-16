from __future__ import annotations

from app.modules.ingestion.source_orchestrator import (
    classify_gmail_sender_family,
    route_calendar_component,
    route_gmail_message,
)


def test_classify_gmail_sender_family_maps_lms_and_course_tools() -> None:
    assert classify_gmail_sender_family(from_header="notifications@instructure.com") == "lms"
    assert classify_gmail_sender_family(from_header="no-reply@gradescope.com") == "course_tools"
    assert classify_gmail_sender_family(from_header="friend@example.com") == "unknown_sender"


def test_route_gmail_message_parse_vs_skip_unknown() -> None:
    parse_decision = route_gmail_message(
        from_header="notifications@instructure.com",
        subject="Course update",
        snippet="Please review the update",
        body_text="General course notice",
        known_course_tokens=set(),
    )
    skip_decision = route_gmail_message(
        from_header="friend@example.com",
        subject="Weekend brunch",
        snippet="See you there",
        body_text="Not a school message.",
        known_course_tokens=set(),
    )

    assert parse_decision.route == "parse"
    assert parse_decision.sender_family == "lms"
    assert skip_decision.route == "skip_unknown"
    assert skip_decision.sender_family == "unknown_sender"


def test_route_calendar_component_routes_work_like_titles() -> None:
    parse_decision = route_calendar_component(
        source_title="Project 1 [CSE100_WI26_A00]",
        source_summary="Project due next week",
    )
    skip_decision = route_calendar_component(
        source_title="Office Hours",
        source_summary="Join office hours this week",
    )

    assert parse_decision.route == "parse"
    assert skip_decision.route == "skip_unknown"
