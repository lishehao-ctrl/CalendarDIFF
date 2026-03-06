from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.modules.notify.interface import ChangeDigestItem
from app.modules.notify.notifier_factory import build_notifier
from app.modules.notify.runtime_context import notification_runtime_context


def _sample_item(event_uid: str) -> ChangeDigestItem:
    return ChangeDigestItem(
        event_uid=event_uid,
        change_type="due_changed",
        course_label="CSE 151A",
        title="Homework 1",
        before_start_at_utc="2026-03-01T17:00:00+00:00",
        after_start_at_utc="2026-03-01T18:00:00+00:00",
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
        input_label="Input 1",
        input_id=1,
        items=[_sample_item("uid-1"), _sample_item("uid-2")],
    )
    assert result.success is True
    assert sink_path.is_file()

    lines = [line for line in sink_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["to_email"] == "student@example.edu"
    assert payload["input_id"] == 1
    assert payload["input_label"] == "Input 1"
    assert payload["item_count"] == 2
    assert sorted(payload["item_event_uids"]) == ["uid-1", "uid-2"]
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
            input_label="Input 2",
            input_id=2,
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
            input_label="Input Parallel",
            input_id=index,
            items=[_sample_item(f"uid-{index}")],
        )
        return result.success

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(_send_one, range(20)))
    assert all(outcomes)

    lines = [line for line in sink_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 20
    parsed = [json.loads(line) for line in lines]
    input_ids = {int(row["input_id"]) for row in parsed}
    assert input_ids == set(range(20))
    get_settings.cache_clear()
