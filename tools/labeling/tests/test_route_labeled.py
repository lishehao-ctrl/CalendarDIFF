from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.labeling.route_labeled import RouteConfig, run_router

ROOT_DIR = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT_DIR / "tools" / "labeling" / "schema" / "email_label.json"

EXPECTED_KEYS = {
    "email_id",
    "label",
    "confidence",
    "reasons",
    "course_hints",
    "event_type",
    "action_items",
    "raw_extract",
    "notes",
}


def make_row(
    email_id: str,
    *,
    label: str = "KEEP",
    confidence: float = 0.9,
    event_type: str | None = "deadline",
    action_items: list[dict[str, Any]] | None = None,
    raw_extract: dict[str, Any] | None = None,
    course_hints: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    if label == "DROP":
        event_type = None
        action_items = []
        raw_extract = {"deadline_text": None, "time_text": None, "location_text": None}

    if action_items is None:
        action_items = [{"action": "Check update", "due_iso": "2026-03-01T23:59:00-08:00", "where": "LMS"}]
    if raw_extract is None:
        raw_extract = {"deadline_text": "due next week", "time_text": "next week", "location_text": "LMS"}
    if course_hints is None:
        course_hints = ["CSE 100"]

    return {
        "email_id": email_id,
        "label": label,
        "confidence": confidence,
        "reasons": ["deterministic test row"],
        "course_hints": course_hints,
        "event_type": event_type,
        "action_items": action_items,
        "raw_extract": raw_extract,
        "notes": notes,
    }


def write_jsonl(path: Path, rows: Sequence[dict[str, Any] | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            if isinstance(row, str):
                handle.write(row + "\n")
            else:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def run_with_rows(
    tmp_path: Path,
    rows: Sequence[dict[str, Any] | str],
    *,
    review_threshold: float = 0.75,
    max_action_items: int = 5,
) -> tuple[dict[str, Any], Path]:
    input_path = tmp_path / "labeled.jsonl"
    outdir = tmp_path / "routes"
    write_jsonl(input_path, rows)
    config = RouteConfig(
        input_path=input_path,
        outdir=outdir,
        schema_path=SCHEMA_PATH,
        review_threshold=review_threshold,
        max_action_items=max_action_items,
        timezone="America/Los_Angeles",
    )
    stats = run_router(config)
    return stats, outdir


def test_routes_basic_mvp(tmp_path: Path) -> None:
    rows = [
        make_row("drop-1", label="DROP"),
        make_row("notify-1", event_type="deadline"),
        make_row("archive-1", event_type="grade", action_items=[]),
        make_row(
            "review-1",
            event_type="exam",
            action_items=[],
            raw_extract={"deadline_text": None, "time_text": None, "location_text": None},
            confidence=0.92,
        ),
    ]
    stats, outdir = run_with_rows(tmp_path, rows)

    drop_rows = read_jsonl(outdir / "drop.jsonl")
    archive_rows = read_jsonl(outdir / "archive.jsonl")
    notify_rows = read_jsonl(outdir / "notify.jsonl")
    review_rows = read_jsonl(outdir / "review.jsonl")

    assert [row["email_id"] for row in drop_rows] == ["drop-1"]
    assert [row["email_id"] for row in archive_rows] == ["archive-1", "review-1"]
    assert [row["email_id"] for row in notify_rows] == ["notify-1"]
    assert [row["email_id"] for row in review_rows] == ["review-1"]
    assert set(notify_rows[0].keys()) == EXPECTED_KEYS
    assert stats["route_counts"] == {"drop": 1, "archive": 2, "notify": 1, "review": 1}


def test_bad_due_iso_triggers_review(tmp_path: Path) -> None:
    row = make_row(
        "bad-due-1",
        event_type="assignment",
        action_items=[{"action": "Submit HW", "due_iso": "not-a-date", "where": "Gradescope"}],
    )
    stats, outdir = run_with_rows(tmp_path, [row])

    archive_rows = read_jsonl(outdir / "archive.jsonl")
    review_rows = read_jsonl(outdir / "review.jsonl")
    assert [item["email_id"] for item in archive_rows] == ["bad-due-1"]
    assert [item["email_id"] for item in review_rows] == ["bad-due-1"]
    assert stats["route_counts"]["review"] == 1


def test_dedup_higher_confidence_wins(tmp_path: Path) -> None:
    low_conf = make_row("dup-1", confidence=0.52, event_type="grade", action_items=[])
    high_conf = make_row("dup-1", confidence=0.88, event_type="deadline")
    stats, outdir = run_with_rows(tmp_path, [low_conf, high_conf])

    archive_rows = read_jsonl(outdir / "archive.jsonl")
    notify_rows = read_jsonl(outdir / "notify.jsonl")

    assert archive_rows == []
    assert [row["email_id"] for row in notify_rows] == ["dup-1"]
    assert notify_rows[0]["confidence"] == 0.88
    assert stats["duplicate_email_id_count"] == 1
    assert any("duplicate_email_id_count=1" in warning for warning in stats["warnings"])


def test_json_parse_error_goes_to_route_errors(tmp_path: Path) -> None:
    rows: list[dict[str, Any] | str] = ['{"email_id":"broken"', make_row("drop-ok", label="DROP")]
    stats, outdir = run_with_rows(tmp_path, rows)

    route_errors = read_jsonl(outdir / "route_errors.jsonl")
    drop_rows = read_jsonl(outdir / "drop.jsonl")

    assert len(route_errors) == 1
    assert route_errors[0]["email_id"] == "unknown"
    assert route_errors[0]["error_type"] == "json_parse_error"
    assert [row["email_id"] for row in drop_rows] == ["drop-ok"]
    assert stats["parse_error_count"] == 1


def test_max_action_items_warning_stats_only(tmp_path: Path) -> None:
    action_items = [
        {"action": f"Task {idx}", "due_iso": "2026-03-01T23:59:00-08:00", "where": "Portal"} for idx in range(6)
    ]
    row = make_row("many-actions", event_type="assignment", action_items=action_items)
    stats, outdir = run_with_rows(tmp_path, [row], max_action_items=5)

    notify_rows = read_jsonl(outdir / "notify.jsonl")
    assert len(notify_rows) == 1
    assert notify_rows[0]["action_items"] == action_items
    assert stats["rows_exceeding_max_action_items"] == 1
    assert any("rows_exceeding_max_action_items=1" in warning for warning in stats["warnings"])


def test_notify_empty_action_items_percent(tmp_path: Path) -> None:
    row_empty = make_row(
        "notify-empty",
        event_type="schedule_change",
        action_items=[],
        raw_extract={"deadline_text": None, "time_text": "Mon 10:00", "location_text": "Zoom"},
    )
    row_full = make_row(
        "notify-full",
        event_type="assignment",
        action_items=[{"action": "Submit", "due_iso": "2026-03-01T23:59:00-08:00", "where": "LMS"}],
    )
    stats, outdir = run_with_rows(tmp_path, [row_empty, row_full])

    notify_rows = read_jsonl(outdir / "notify.jsonl")
    assert len(notify_rows) == 2
    assert stats["notify_empty_action_items_percent"] == 50.0
