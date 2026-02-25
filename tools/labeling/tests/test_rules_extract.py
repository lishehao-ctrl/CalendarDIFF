from __future__ import annotations

import json
import mailbox
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from tools.labeling.rules_extract import RuleExtractConfig, analyze_email_rules, run_rules_extract

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


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _build_jsonl_config(tmp_path: Path) -> RuleExtractConfig:
    return RuleExtractConfig(
        input_jsonl=tmp_path / "emails.jsonl",
        input_mbox=None,
        output_path=tmp_path / "rules_labeled.jsonl",
        errors_path=tmp_path / "rules_errors.jsonl",
        schema_path=SCHEMA_PATH,
        timezone="America/Los_Angeles",
    )


def _build_mbox(path: Path, *, count: int) -> None:
    box = mailbox.mbox(str(path), create=True)
    try:
        for idx in range(1, count + 1):
            message = EmailMessage()
            message["From"] = "instructor@school.edu"
            message["To"] = "student@example.edu"
            message["Subject"] = f"[CSE 100] Homework {idx} deadline moved"
            message["Date"] = "Tue, 20 Feb 2026 10:00:00 -0800"
            message["Message-ID"] = f"<msg-{idx}@example.edu>"
            message.set_content("Homework deadline is moved to 2026-02-22T23:59:00-08:00.")
            box.add(message)
        box.flush()
    finally:
        box.close()


def test_rules_extract_jsonl_enforces_contract_and_is_deterministic(tmp_path: Path) -> None:
    config = _build_jsonl_config(tmp_path)
    _write_jsonl(
        config.input_jsonl,
        [
            {
                "email_id": "email-1",
                "from": "cse@school.edu",
                "subject": "[CSE 100] HW1 deadline extension",
                "date": "2026-02-20T10:00:00-08:00",
                "body_text": "Homework 1 deadline moved to 2026-02-22T23:59:00-08:00. Submit on Gradescope.",
            },
            {
                "email_id": "email-2",
                "from": "noreply@piazza.com",
                "subject": "Daily Digest for CSE 100",
                "date": "2026-02-20T18:00:00-08:00",
                "body_text": "Daily digest and newsletter summary. No action required.",
            },
            {
                "email_id": "email-3",
                "subject": "broken row",
            },
            {
                "email_id": "email-4",
                "from": "staff@school.edu",
                "subject": "Class moved to another room",
                "date": "2026-02-21T09:00:00-08:00",
                "body_text": "Class moved to room CENTR 222 at 10:00 AM.",
            },
        ],
    )

    summary = run_rules_extract(config)
    out_rows = _read_jsonl(config.output_path)
    err_rows = _read_jsonl(config.errors_path)

    assert summary["total_in"] == 4
    assert summary["output_rows"] == 3
    assert summary["error_count"] >= 1

    by_id = {row["email_id"]: row for row in out_rows}
    for row in out_rows:
        assert set(row.keys()) == EXPECTED_KEYS

    assert by_id["email-1"]["label"] == "KEEP"
    assert by_id["email-1"]["event_type"] == "schedule_change"
    assert isinstance(by_id["email-1"]["action_items"], list)
    assert by_id["email-1"]["raw_extract"]["time_text"] is not None

    assert by_id["email-2"]["label"] == "DROP"
    assert by_id["email-2"]["event_type"] is None
    assert by_id["email-2"]["action_items"] == []

    assert by_id["email-4"]["label"] == "KEEP"
    assert by_id["email-4"]["event_type"] == "schedule_change"

    assert any(item["error_type"] == "input_validation" for item in err_rows)


def test_rules_extract_mbox_path_row_count_parity(tmp_path: Path) -> None:
    mbox_path = tmp_path / "emails.mbox"
    _build_mbox(mbox_path, count=2)

    config = RuleExtractConfig(
        input_jsonl=None,
        input_mbox=mbox_path,
        output_path=tmp_path / "rules_labeled.jsonl",
        errors_path=tmp_path / "rules_errors.jsonl",
        schema_path=SCHEMA_PATH,
        timezone="America/Los_Angeles",
    )

    summary = run_rules_extract(config)
    out_rows = _read_jsonl(config.output_path)

    assert summary["input_mode"] == "mbox"
    assert summary["total_in"] == 2
    assert summary["output_rows"] == 2
    assert len(out_rows) == 2
    assert all(row["label"] == "KEEP" for row in out_rows)


def test_schema_invalid_candidate_is_diverted_to_error_sidecar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _build_jsonl_config(tmp_path)
    _write_jsonl(
        config.input_jsonl,
        [
            {
                "email_id": "broken-schema",
                "subject": "s",
                "body_text": "b",
            }
        ],
    )

    def fake_build_row(*args: Any, **kwargs: Any) -> dict[str, Any]:
        _ = (args, kwargs)
        return {
            "email_id": "broken-schema",
            "label": "MAYBE",
            "confidence": 0.5,
            "reasons": [],
            "course_hints": [],
            "event_type": None,
            "action_items": [],
            "raw_extract": {"deadline_text": None, "time_text": None, "location_text": None},
            "notes": None,
        }

    monkeypatch.setattr("tools.labeling.rules_extract._build_row", fake_build_row)
    summary = run_rules_extract(config)

    out_rows = _read_jsonl(config.output_path)
    err_rows = _read_jsonl(config.errors_path)
    assert summary["output_rows"] == 0
    assert out_rows == []
    assert any(item["error_type"] == "schema_validation" for item in err_rows)


def test_analyze_email_rules_explainability_and_mdy_time_parse() -> None:
    analysis = analyze_email_rules(
        subject="[CSE151A] Deadline pushed back",
        body_text=(
            "Please complete the submission. The deadline is pushed back to 03/14 11:59 PM PT. "
            "Room change: CENTR 222."
        ),
        date_hint="2026-03-01T10:00:00-08:00",
        timezone=ZoneInfo("America/Los_Angeles"),
    )

    assert analysis.label == "KEEP"
    assert analysis.event_type == "schedule_change"
    assert analysis.event_flags["schedule_change"] is True
    assert analysis.raw_extract["deadline_text"] is not None
    assert analysis.action_items
    assert analysis.action_items[0]["due_iso"] is not None
    assert "CSE 151A" in analysis.course_hints
    assert any(item["rule"] == "schedule_change" for item in [{"rule": k} for k in analysis.matched_snippets.keys()])


def test_analyze_email_rules_drop_reason_codes_for_digest() -> None:
    analysis = analyze_email_rules(
        subject="Recent Canvas Notifications",
        body_text="Daily digest and newsletter summary. No action required.",
        date_hint="2026-02-20T18:00:00-08:00",
        timezone=ZoneInfo("America/Los_Angeles"),
    )

    assert analysis.label == "DROP"
    assert "noise_digest" in analysis.drop_reason_codes
    assert "no_actionable_signal" in analysis.drop_reason_codes
