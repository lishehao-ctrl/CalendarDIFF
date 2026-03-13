from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.modules.common.event_display import EventDisplay
from app.modules.notify.interface import ChangeDigestItem
from app.modules.notify.notifier_factory import build_notifier
from app.modules.notify.runtime_context import notification_runtime_context


def _display(course_display: str, family_name: str, ordinal: int | None = None) -> EventDisplay:
    return EventDisplay(
        course_display=course_display,
        family_name=family_name,
        ordinal=ordinal,
        display_label=f"{course_display} · {family_name}{f' {ordinal}' if ordinal is not None else ''}",
    )


def _sample_item(entity_uid: str) -> ChangeDigestItem:
    return ChangeDigestItem(
        entity_uid=entity_uid,
        change_type="due_changed",
        before_display=_display("CSE 151A", "Homework", 1),
        after_display=_display("CSE 151A", "Homework", 1),
        before_due_at="2026-03-01T17:00:00+00:00",
        after_due_at="2026-03-01T18:00:00+00:00",
        before_time_precision="datetime",
        after_time_precision="datetime",
        delta_seconds=3600,
        detected_at=datetime.now(timezone.utc),
        evidence_path="evidence/ics/demo.ics",
    )


def test_jsonl_notifier_writes_expected_fields(monkeypatch, tmp_path: Path) -> None:
    sink_path = tmp_path / "notify_sink.jsonl"
    monkeypatch.setenv("NOTIFY_SINK_MODE", "jsonl")
    monkeypatch.setenv("NOTIFY_JSONL_PATH", str(sink_path))
    get_settings.cache_clear()

    notifier = build_notifier()
    result = notifier.send_changes_digest(
        to_email="student@example.edu",
        review_label="1 new review",
        user_id=1,
        items=[_sample_item("uid-1"), _sample_item("uid-2")],
    )
    assert result.success is True
    assert sink_path.is_file()

    lines = [line for line in sink_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["to_email"] == "student@example.edu"
    assert payload["user_id"] == 1
    assert payload["review_label"] == "1 new review"
    assert payload["item_count"] == 2
    assert sorted(payload["item_entity_uids"]) == ["uid-1", "uid-2"]
    assert payload["item_display_labels"] == ["CSE 151A · Homework 1", "CSE 151A · Homework 1"]
    assert payload["run_id"] is None
    assert payload["semester"] is None
    assert payload["batch"] is None
    get_settings.cache_clear()


def test_jsonl_notifier_includes_runtime_context(monkeypatch, tmp_path: Path) -> None:
    sink_path = tmp_path / "notify_sink_context.jsonl"
    monkeypatch.setenv("NOTIFY_SINK_MODE", "jsonl")
    monkeypatch.setenv("NOTIFY_JSONL_PATH", str(sink_path))
    get_settings.cache_clear()

    notifier = build_notifier()
    with notification_runtime_context(run_id="semester-demo-run", semester=2, batch=7):
        result = notifier.send_changes_digest(
            to_email="student@example.edu",
            review_label="1 new review",
            user_id=2,
            items=[_sample_item("uid-ctx")],
        )

    assert result.success is True
    payload = json.loads(sink_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["run_id"] == "semester-demo-run"
    assert payload["semester"] == 2
    assert payload["batch"] == 7
    get_settings.cache_clear()


def test_jsonl_notifier_thread_safe_append(monkeypatch, tmp_path: Path) -> None:
    sink_path = tmp_path / "notify_sink_parallel.jsonl"
    monkeypatch.setenv("NOTIFY_SINK_MODE", "jsonl")
    monkeypatch.setenv("NOTIFY_JSONL_PATH", str(sink_path))
    get_settings.cache_clear()
    notifier = build_notifier()

    def _send_one(index: int) -> bool:
        result = notifier.send_changes_digest(
            to_email=f"student-{index}@example.edu",
            review_label="1 new review",
            user_id=index,
            items=[_sample_item(f"uid-{index}")],
        )
        return result.success

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(_send_one, range(20)))
    assert all(outcomes)

    lines = [line for line in sink_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 20
    parsed = [json.loads(line) for line in lines]
    user_ids = {int(row["user_id"]) for row in parsed}
    assert user_ids == set(range(20))
    get_settings.cache_clear()
