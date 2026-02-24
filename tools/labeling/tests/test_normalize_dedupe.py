from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.labeling.normalize_labeled import NormalizeConfig, run_normalization_pipeline

ROOT_DIR = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT_DIR / "tools" / "labeling" / "schema" / "email_label.json"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_row(email_id: str, *, label: str, confidence: float, event_type: str | None = "deadline") -> dict[str, Any]:
    if label == "DROP":
        event_type = None
        action_items: list[dict[str, Any]] = []
    else:
        action_items = [{"action": "Submit HW", "due_iso": "2026-03-01T23:59:00-08:00", "where": "LMS"}]
    return {
        "email_id": email_id,
        "label": label,
        "confidence": confidence,
        "reasons": ["test"],
        "course_hints": ["CSE 100"],
        "event_type": event_type,
        "action_items": action_items,
        "raw_extract": {"deadline_text": "deadline", "time_text": "tomorrow", "location_text": "LMS"},
        "notes": None,
    }


def test_normalize_dedupe_rules(tmp_path: Path) -> None:
    input_path = tmp_path / "labeled.jsonl"
    output_path = tmp_path / "normalized.jsonl"
    errors_path = tmp_path / "normalize_errors.jsonl"
    rescue_out_path = tmp_path / "rescue_applied.jsonl"

    rows = [
        make_row("tie-id", label="DROP", confidence=0.8),
        make_row("tie-id", label="KEEP", confidence=0.8),  # tie -> KEEP wins
        make_row("high-id", label="KEEP", confidence=0.6),
        make_row("high-id", label="DROP", confidence=0.9),  # higher confidence wins
    ]
    write_jsonl(input_path, rows)

    config = NormalizeConfig(
        input_path=input_path,
        output_path=output_path,
        errors_path=errors_path,
        dedupe=True,
        max_action_items=5,
        rescue_llm=False,
        rescue_out_path=rescue_out_path,
        timezone="America/Los_Angeles",
        schema_path=SCHEMA_PATH,
    )
    summary = run_normalization_pipeline(config)
    normalized = read_jsonl(output_path)

    assert summary["total_in"] == 4
    assert summary["normalized_out"] == 2
    assert summary["dedupe_count"] == 2

    by_id = {row["email_id"]: row for row in normalized}
    assert by_id["tie-id"]["label"] == "KEEP"
    assert by_id["tie-id"]["confidence"] == 0.8

    assert by_id["high-id"]["label"] == "DROP"
    assert by_id["high-id"]["confidence"] == 0.9
    assert by_id["high-id"]["action_items"] == []
    assert by_id["high-id"]["event_type"] is None
