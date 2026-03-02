from __future__ import annotations

from app.modules.ingestion.eval.ics_runner import infer_ics_diff
from app.modules.ingestion.eval.mail_runner import predict_mail_from_records


def test_predict_mail_from_records_picks_highest_confidence_and_maps_other_to_drop() -> None:
    records = [
        {
            "record_type": "gmail.message.extracted",
            "payload": {
                "event_type": "deadline",
                "confidence": 0.55,
            },
        },
        {
            "record_type": "gmail.message.extracted",
            "payload": {
                "event_type": "other",
                "confidence": 0.95,
            },
        },
    ]

    label, event_type = predict_mail_from_records(records=records)

    assert label == "DROP"
    assert event_type is None


def test_predict_mail_from_records_uses_first_on_confidence_tie() -> None:
    records = [
        {
            "record_type": "gmail.message.extracted",
            "payload": {
                "event_type": "exam",
                "confidence": 0.8,
            },
        },
        {
            "record_type": "gmail.message.extracted",
            "payload": {
                "event_type": "deadline",
                "confidence": 0.8,
            },
        },
    ]

    label, event_type = predict_mail_from_records(records=records)

    assert label == "KEEP"
    assert event_type == "exam"


def test_predict_mail_from_records_empty_defaults_to_drop() -> None:
    label, event_type = predict_mail_from_records(records=[])

    assert label == "DROP"
    assert event_type is None


def test_infer_ics_diff_due_changed_has_priority() -> None:
    before_events = {
        "uid-1": {"start_at": "2026-03-01T10:00:00+00:00", "end_at": "2026-03-01T11:00:00+00:00"},
    }
    after_events = {
        "uid-1": {"start_at": "2026-03-01T12:00:00+00:00", "end_at": "2026-03-01T13:00:00+00:00"},
        "uid-2": {"start_at": "2026-03-02T10:00:00+00:00", "end_at": "2026-03-02T11:00:00+00:00"},
    }

    diff_class, changed_uids = infer_ics_diff(before_events=before_events, after_events=after_events)

    assert diff_class == "DUE_CHANGED"
    assert changed_uids == ["uid-1"]


def test_infer_ics_diff_created_removed_and_no_change() -> None:
    created_class, created_uids = infer_ics_diff(
        before_events={},
        after_events={"uid-new": {"start_at": "a", "end_at": "b"}},
    )
    assert created_class == "CREATED"
    assert created_uids == ["uid-new"]

    removed_class, removed_uids = infer_ics_diff(
        before_events={"uid-old": {"start_at": "a", "end_at": "b"}},
        after_events={},
    )
    assert removed_class == "REMOVED_CANDIDATE"
    assert removed_uids == ["uid-old"]

    unchanged_class, unchanged_uids = infer_ics_diff(
        before_events={"uid-1": {"start_at": "a", "end_at": "b"}},
        after_events={"uid-1": {"start_at": "a", "end_at": "b"}},
    )
    assert unchanged_class == "NO_CHANGE"
    assert unchanged_uids == []
