from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.labeling.normalize_labeled import NormalizeConfig, run_normalization_pipeline

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


def write_jsonl(path: Path, rows: list[dict[str, Any] | str]) -> None:
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
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_config(tmp_path: Path) -> NormalizeConfig:
    return NormalizeConfig(
        input_path=tmp_path / "labeled.jsonl",
        output_path=tmp_path / "normalized.jsonl",
        errors_path=tmp_path / "normalize_errors.jsonl",
        dedupe=False,
        max_action_items=5,
        rescue_llm=False,
        rescue_out_path=tmp_path / "rescue_applied.jsonl",
        timezone="America/Los_Angeles",
        schema_path=SCHEMA_PATH,
    )


def test_normalize_basic_coercions(tmp_path: Path) -> None:
    rows: list[dict[str, Any] | str] = [
        '{"email_id": "broken"',
        {
            "email_id": "new-1",
            "label": "keep",
            "confidence": "1.2",
            "reasons": ["r1", "r2", "r3", "r4"],
            "course_hints": "CSE 100",
            "event_type": "ddl",
            "action_items": "wrong_type",
            "raw_extract": None,
            "notes": 123,
            "extra_field": "should be dropped",
        },
        {
            "email_id": "drop-1",
            "label": False,
            "confidence": -0.8,
            "reasons": "not actionable",
            "course_hints": None,
            "event_type": "deadline",
            "action_items": [{"action": "do x", "due_iso": "2026-02-10T00:00:00-08:00", "where": "x"}],
            "raw_extract": {"deadline_text": "tomorrow", "time_text": "tomorrow", "location_text": "web"},
            "notes": None,
        },
        {
            "email_id": "legacy-1",
            "keep": True,
            "category": "required_action",
            "confidence": 0.71,
            "reasons": "Please submit via form",
            "candidates": [
                {
                    "course_hint": "CSE 120",
                    "item_title_hint": "Quiz 1 regrade form",
                    "new_time": "2026-03-12T23:59:00-08:00",
                    "evidence_spans": ["Submit by Thursday 11:59 PM"],
                }
            ],
        },
    ]
    config = build_config(tmp_path)
    write_jsonl(config.input_path, rows)

    summary = run_normalization_pipeline(config)
    normalized_rows = read_jsonl(config.output_path)
    error_rows = read_jsonl(config.errors_path)

    assert summary["total_in"] == 4
    assert summary["normalized_out"] == 3
    assert summary["error_count"] >= 2
    assert summary["rescue_applied_count"] == 0
    assert summary["dedupe_count"] == 0

    by_id = {row["email_id"]: row for row in normalized_rows}
    assert set(by_id) == {"new-1", "drop-1", "legacy-1"}
    for row in normalized_rows:
        assert set(row.keys()) == EXPECTED_KEYS

    new_row = by_id["new-1"]
    assert new_row["label"] == "KEEP"
    assert new_row["confidence"] == 1.0
    assert new_row["event_type"] == "deadline"
    assert len(new_row["reasons"]) == 3
    assert new_row["course_hints"] == ["CSE 100"]
    assert new_row["action_items"] == []
    assert new_row["raw_extract"] == {"deadline_text": None, "time_text": None, "location_text": None}
    assert new_row["notes"] == "123"

    drop_row = by_id["drop-1"]
    assert drop_row["label"] == "DROP"
    assert drop_row["event_type"] is None
    assert drop_row["action_items"] == []
    assert drop_row["confidence"] == 0.0

    legacy_row = by_id["legacy-1"]
    assert legacy_row["label"] == "KEEP"
    assert legacy_row["event_type"] == "action_required"
    assert legacy_row["course_hints"] == ["CSE 120"]
    assert len(legacy_row["action_items"]) == 1
    assert legacy_row["action_items"][0]["action"] == "Quiz 1 regrade form"
    assert legacy_row["raw_extract"]["deadline_text"] == "Submit by Thursday 11:59 PM"

    assert any(item["error_type"] == "json_parse" for item in error_rows)
    assert any(item["error_type"] == "coercion_warning" for item in error_rows)
