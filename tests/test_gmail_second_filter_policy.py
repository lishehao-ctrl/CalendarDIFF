from __future__ import annotations

from app.core.config import get_settings
from app.modules.runtime.connectors import gmail_second_filter as second_filter
from app.modules.runtime.connectors.gmail_second_filter import (
    SAFE_NON_TARGET_REASON_CODES,
    classify_safe_non_target_heuristic,
    run_gmail_second_filter,
    should_enforce_gmail_second_filter,
)


def test_safe_non_target_reason_codes_include_expanded_runtime_families() -> None:
    assert {
        "jobs",
        "package_subscription",
        "newsletter_digest",
        "lms_wrapper_noise",
        "calendar_wrapper_noise",
        "student_services_noise",
        "academic_non_target_explicit_no_change",
    }.issubset(SAFE_NON_TARGET_REASON_CODES)


def test_classify_safe_non_target_heuristic_matches_jobs_family() -> None:
    match = classify_safe_non_target_heuristic(
        from_header="Vertex Recruiting <talent@careers.example.com>",
        subject="Internship Application submission update",
        snippet="Recruiting logistics are unrelated to monitored course deadlines.",
        body_text="Recruiting workflow update. This mailbox is not monitored.",
        known_course_tokens=None,
    )
    assert match.reason_code == "jobs"
    assert match.risk_band == "safe"


def test_classify_safe_non_target_heuristic_matches_student_services_family() -> None:
    match = classify_safe_non_target_heuristic(
        from_header="Academic Advising <services@students.example.edu>",
        subject="Advising Follow-Up assignment follow-up",
        snippet="Student services notice. Please use the student services portal for follow-up.",
        body_text="Student services notice. Advising and paperwork reminders are non-target.",
        known_course_tokens=None,
    )
    assert match.reason_code == "student_services_noise"
    assert match.risk_band == "safe"


def test_classify_safe_non_target_heuristic_matches_calendar_wrapper_family() -> None:
    match = classify_safe_non_target_heuristic(
        from_header="Events Calendar <calendar@events.example.com>",
        subject="Fwd: Calendar: Invite Follow-Up deadline",
        snippet="Calendar forwarding summary invite reminders are wrapper clutter rather than canonical academic signals.",
        body_text="Calendar forwarding summary. Manage calendar. Invite reminders are wrapper clutter rather than canonical academic signals.",
        known_course_tokens=None,
    )
    assert match.reason_code == "calendar_wrapper_noise"
    assert match.risk_band == "safe"


def test_classify_safe_non_target_heuristic_matches_academic_explicit_no_change_family() -> None:
    match = classify_safe_non_target_heuristic(
        from_header="Registrar Updates <noreply@campus.example.edu>",
        subject="[MATH18] section waitlist admin and submission note",
        snippet="The graded submission schedule is unchanged.",
        body_text="Discussion waitlist handling changed and the graded submission schedule is unchanged. Lab section moved, report unchanged.",
        known_course_tokens=None,
    )
    assert match.reason_code == "academic_non_target_explicit_no_change"
    assert match.risk_band == "safe"


def test_run_gmail_second_filter_suppresses_safe_jobs_family_when_hf_agrees(monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_SECONDARY_FILTER_MODE", "enforce")
    monkeypatch.setenv("GMAIL_SECONDARY_FILTER_PROVIDER", "huggingface_endpoint")
    monkeypatch.setenv("GMAIL_SECONDARY_FILTER_ENDPOINT_URL", "https://example.com/infer")
    monkeypatch.setenv("HFTOKEN", "test-token")
    get_settings.cache_clear()
    monkeypatch.setattr(second_filter, "_invoke_huggingface_endpoint", lambda **kwargs: ("non_target", 0.9997))
    decision = run_gmail_second_filter(
        from_header="Vertex Recruiting <talent@careers.example.com>",
        subject="Internship Application submission update",
        snippet="Recruiting logistics are unrelated to monitored course deadlines.",
        body_text="Recruiting workflow update. This mailbox is not monitored.",
        label_ids=["INBOX"],
        known_course_tokens=None,
    )
    assert decision.reason_code == "jobs"
    assert decision.would_suppress is True
    assert should_enforce_gmail_second_filter(decision) is True
    get_settings.cache_clear()


def test_run_gmail_second_filter_does_not_suppress_high_risk_due_change_even_when_hf_says_non_target(monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_SECONDARY_FILTER_MODE", "enforce")
    monkeypatch.setenv("GMAIL_SECONDARY_FILTER_PROVIDER", "huggingface_endpoint")
    monkeypatch.setenv("GMAIL_SECONDARY_FILTER_ENDPOINT_URL", "https://example.com/infer")
    monkeypatch.setenv("HFTOKEN", "test-token")
    get_settings.cache_clear()
    monkeypatch.setattr(second_filter, "_invoke_huggingface_endpoint", lambda **kwargs: ("non_target", 0.9999))
    decision = run_gmail_second_filter(
        from_header="cse120-staff@courses.example.edu",
        subject="[CSE120] Homework 4 due date updated",
        snippet="Homework 4 is now due Thursday at 11:59 PM.",
        body_text="Homework 4 is now due Thursday instead of Tuesday at 11:59 PM.",
        label_ids=["INBOX"],
        known_course_tokens={"cse 120", "cse120"},
    )
    assert decision.risk_band == "high_risk"
    assert decision.would_suppress is False
    assert should_enforce_gmail_second_filter(decision) is False
    get_settings.cache_clear()


def test_run_gmail_second_filter_bypasses_hf_for_small_diff_batch(monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_SECONDARY_FILTER_MODE", "enforce")
    monkeypatch.setenv("GMAIL_SECONDARY_FILTER_PROVIDER", "huggingface_endpoint")
    monkeypatch.setenv("GMAIL_SECONDARY_FILTER_ENDPOINT_URL", "https://example.com/infer")
    monkeypatch.setenv("HFTOKEN", "test-token")
    get_settings.cache_clear()

    def _should_not_run(**kwargs):
        raise AssertionError("hf endpoint should not run for diff batches <= 10")

    monkeypatch.setattr(second_filter, "_invoke_huggingface_endpoint", _should_not_run)
    decision = run_gmail_second_filter(
        from_header="Vertex Recruiting <talent@careers.example.com>",
        subject="Internship Application submission update",
        snippet="Recruiting logistics are unrelated to monitored course deadlines.",
        body_text="Recruiting workflow update. This mailbox is not monitored.",
        label_ids=["INBOX"],
        known_course_tokens=None,
        diff_message_count=10,
    )
    assert decision.action == "abstain"
    assert decision.reason_code == "secondary_filter_small_batch_bypass"
    assert should_enforce_gmail_second_filter(decision) is False
    get_settings.cache_clear()
