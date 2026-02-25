from __future__ import annotations

import json
import mailbox
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from tools.labeling.inspect_fn import InspectFnConfig, run_inspect


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _build_pred_row(email_id: str, *, label: str = "DROP", event_type: str | None = None) -> dict[str, Any]:
    return {
        "email_id": email_id,
        "label": label,
        "event_type": event_type,
        "confidence": 0.8,
        "reasons": [],
        "course_hints": [],
        "action_items": [],
        "raw_extract": {"deadline_text": None, "time_text": None, "location_text": None},
        "notes": None,
    }


def _build_silver_row(email_id: str, *, label: str = "KEEP", event_type: str | None = "action_required") -> dict[str, Any]:
    return {
        "email_id": email_id,
        "label": label,
        "event_type": event_type,
        "confidence": 0.9,
        "reasons": [],
        "course_hints": [],
        "action_items": [],
        "raw_extract": {"deadline_text": None, "time_text": None, "location_text": None},
        "notes": None,
    }


def test_inspect_fn_jsonl_batch_outputs_expected_fields(tmp_path: Path) -> None:
    fn_path = tmp_path / "fn.jsonl"
    emails_path = tmp_path / "emails.jsonl"
    pred_path = tmp_path / "pred.jsonl"
    silver_path = tmp_path / "silver.jsonl"
    out_jsonl = tmp_path / "inspect.jsonl"
    out_md = tmp_path / "inspect.md"

    fn_rows = [{"email_id": f"email-{idx}"} for idx in range(12)]
    email_rows = [
        {
            "email_id": f"email-{idx}",
            "from": "staff@school.edu",
            "subject": f"[CSE151A] assignment {idx} moved to new room",
            "date": "2026-02-20T10:00:00-08:00",
            "body_text": "Room change: now in CENTR 101. Submit by 02/22 11:59 PM PT.",
        }
        for idx in range(12)
    ]

    _write_jsonl(fn_path, fn_rows)
    _write_jsonl(emails_path, email_rows)
    _write_jsonl(pred_path, [_build_pred_row(f"email-{idx}") for idx in range(12)])
    _write_jsonl(silver_path, [_build_silver_row(f"email-{idx}") for idx in range(12)])

    config = InspectFnConfig(
        fn_path=fn_path,
        emails_jsonl=emails_path,
        input_mbox=None,
        pred_path=pred_path,
        silver_path=silver_path,
        out_jsonl=out_jsonl,
        out_md=out_md,
        timezone="America/Los_Angeles",
        batch_size=10,
        batch_index=0,
        snippet_head_chars=120,
        snippet_tail_chars=120,
    )
    summary = run_inspect(config)

    assert summary["batch_count"] == 10
    rows = _read_jsonl(out_jsonl)
    assert len(rows) == 10
    row = rows[0]
    assert "matched_rules" in row
    assert "miss_reasons" in row
    assert "course_hints_current" in row
    assert "due_parse_current" in row
    assert out_md.is_file()
    markdown_text = out_md.read_text(encoding="utf-8")
    assert "# FN Inspect Batch" in markdown_text
    assert "Snippet Head" in markdown_text


def test_inspect_fn_mbox_input_works(tmp_path: Path) -> None:
    fn_path = tmp_path / "fn.jsonl"
    pred_path = tmp_path / "pred.jsonl"
    silver_path = tmp_path / "silver.jsonl"
    out_jsonl = tmp_path / "inspect.jsonl"
    out_md = tmp_path / "inspect.md"
    mbox_path = tmp_path / "emails.mbox"

    box = mailbox.mbox(str(mbox_path), create=True)
    try:
        message = EmailMessage()
        message["From"] = "instructor@school.edu"
        message["To"] = "student@example.edu"
        message["Subject"] = "Class rescheduled and pushed back"
        message["Date"] = "Tue, 20 Feb 2026 10:00:00 -0800"
        message["Message-ID"] = "<msg-1@example.edu>"
        message.set_content("Class moved to 03/05 at 9:00 AM PT. Room change to CSB 120.")
        box.add(message)
        box.flush()
    finally:
        box.close()

    _write_jsonl(fn_path, [{"email_id": "msg-1@example.edu"}])
    _write_jsonl(pred_path, [_build_pred_row("msg-1@example.edu", label="DROP", event_type=None)])
    _write_jsonl(silver_path, [_build_silver_row("msg-1@example.edu", label="KEEP", event_type="schedule_change")])

    config = InspectFnConfig(
        fn_path=fn_path,
        emails_jsonl=None,
        input_mbox=mbox_path,
        pred_path=pred_path,
        silver_path=silver_path,
        out_jsonl=out_jsonl,
        out_md=out_md,
        timezone="America/Los_Angeles",
        batch_size=10,
        batch_index=0,
        snippet_head_chars=120,
        snippet_tail_chars=120,
    )
    summary = run_inspect(config)
    assert summary["batch_count"] == 1

    rows = _read_jsonl(out_jsonl)
    assert len(rows) == 1
    assert rows[0]["email_id"] == "msg-1@example.edu"
    assert isinstance(rows[0]["matched_rules"], list)
