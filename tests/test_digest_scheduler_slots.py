from __future__ import annotations

from datetime import datetime, timezone

from app.modules.notify.digest_service import compute_due_slots


def test_compute_due_slots_marks_past_time_due() -> None:
    now_utc = datetime(2026, 2, 24, 17, 1, tzinfo=timezone.utc)  # 09:01 in Los Angeles (PST)
    local_date, due = compute_due_slots(
        now_utc=now_utc,
        timezone_name="America/Los_Angeles",
        digest_times=["09:00", "21:00"],
        sent_slots=set(),
    )
    assert local_date.isoformat() == "2026-02-24"
    assert due == ["09:00"]


def test_compute_due_slots_respects_sent_slots() -> None:
    now_utc = datetime(2026, 2, 24, 17, 1, tzinfo=timezone.utc)
    local_date, due = compute_due_slots(
        now_utc=now_utc,
        timezone_name="America/Los_Angeles",
        digest_times=["09:00"],
        sent_slots={"2026-02-24|09:00"},
    )
    assert local_date.isoformat() == "2026-02-24"
    assert due == []
