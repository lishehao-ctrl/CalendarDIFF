from __future__ import annotations

from scripts.evaluate_local_email_prefilter import evaluate_prefilter_rows, tokens_for_course_text


def test_prefilter_evaluation_reports_deterministic_counts() -> None:
    rows = [
        {
            "sample_id": "target-1",
            "label_ids": ["INBOX"],
            "from_header": "professor@school.edu",
            "subject": "Homework deadline reminder",
            "snippet": "Assignment due Friday",
            "body_text": "Please note the homework deadline has moved for CSE 120.",
            "course_label": "CSE120",
            "prefilter_expected_route": "parse",
            "prefilter_reason_family": "target_course_signal",
            "prefilter_target_class": "target_signal",
            "expected_semantic_event_draft": {
                "course_dept": "CSE",
                "course_number": 120,
                "course_suffix": "",
            },
        },
        {
            "sample_id": "noise-1",
            "label_ids": ["INBOX"],
            "from_header": "security@auth.example.com",
            "subject": "Account verification due",
            "snippet": "Review your sign-in alert",
            "body_text": "This is a security alert and not a course message.",
            "prefilter_expected_route": "skip_unknown",
            "prefilter_reason_family": "security",
            "prefilter_target_class": "non_target",
        },
        {
            "sample_id": "noise-2",
            "label_ids": ["INBOX"],
            "from_header": "friend@example.com",
            "subject": "Lab moved to Thursday",
            "snippet": "lab update",
            "body_text": "The lab section has a room change.",
            "course_label": "CSE120",
            "prefilter_expected_route": "skip_unknown",
            "prefilter_reason_family": "target_course_lab_noise",
            "prefilter_target_class": "non_target",
        },
    ]

    report = evaluate_prefilter_rows(rows)

    assert report["overall"]["sample_count"] == 3
    assert report["overall"]["parse_count"] == 1
    assert report["overall"]["skip_count"] == 2
    assert report["overall"]["expected_route_accuracy"] == 1.0
    assert report["target_recall"]["recall"] == 1.0
    assert report["non_target_interception"]["interception_rate"] == 1.0
    assert report["by_reason_family"]["security"]["skip_count"] == 1
    assert report["by_reason_family"]["target_course_lab_noise"]["skip_count"] == 1


def test_prefilter_evaluation_derives_compact_and_spaced_course_tokens() -> None:
    tokens = tokens_for_course_text("CSE120")
    assert "cse120" in tokens
    assert "cse 120" in tokens
