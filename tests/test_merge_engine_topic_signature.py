from __future__ import annotations

from datetime import datetime, timezone

from app.modules.core_ingest.merge_engine import (
    build_merge_key,
    choose_primary_observation,
    normalize_course_label,
    normalize_topic_signature,
)


def test_normalize_course_label_alias_forms_match() -> None:
    canonical = normalize_course_label("CSE8A")
    assert canonical == normalize_course_label("cSe_8A")
    assert canonical == normalize_course_label("CSE 8A")
    assert canonical == normalize_course_label("CSE-8A")


def test_normalize_topic_signature_strips_forwarding_noise() -> None:
    first = normalize_topic_signature("[Update] CSE 8A HW1 deadline moved")
    second = normalize_topic_signature("Fwd: cSe_8A hw-1 reminder due")
    assert first == second


def test_build_merge_key_ignores_due_date_for_same_topic() -> None:
    first_due = datetime(2026, 3, 10, 23, 59, tzinfo=timezone.utc)
    second_due = datetime(2026, 3, 12, 20, 30, tzinfo=timezone.utc)

    key_one = build_merge_key(
        course_label="CSE8A",
        title="CSE8A HW1 Deadline",
        start_at=first_due,
        end_at=first_due,
        event_type=None,
    )
    key_two = build_merge_key(
        course_label="cSe_8A",
        title="[Reminder] CSE 8A hw-1 due",
        start_at=second_due,
        end_at=second_due,
        event_type=None,
    )

    assert key_one == key_two


def test_build_merge_key_splits_different_assignments() -> None:
    due = datetime(2026, 3, 10, 23, 59, tzinfo=timezone.utc)

    hw1 = build_merge_key(
        course_label="CSE8A",
        title="CSE8A HW1 Deadline",
        start_at=due,
        end_at=due,
        event_type=None,
    )
    hw2 = build_merge_key(
        course_label="CSE8A",
        title="CSE8A HW2 Deadline",
        start_at=due,
        end_at=due,
        event_type=None,
    )

    assert hw1 != hw2


def test_choose_primary_observation_prefers_newer_observation() -> None:
    older = {
        "source_kind": "email",
        "observed_at": datetime(2026, 3, 10, 23, 59, tzinfo=timezone.utc),
        "event_payload": {"confidence": 0.99, "title": "old"},
    }
    newer = {
        "source_kind": "calendar",
        "observed_at": datetime(2026, 3, 11, 21, 0, tzinfo=timezone.utc),
        "event_payload": {"confidence": 0.7, "title": "new"},
    }
    chosen = choose_primary_observation([older, newer])
    assert chosen is newer
