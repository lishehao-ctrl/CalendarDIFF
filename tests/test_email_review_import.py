from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select

from app.db.models import EmailActionItem, EmailMessage, EmailRoute, EmailRuleAnalysis, EmailRuleLabel
from tools.rules_labeling.import_rules_to_db import run_import


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_import_rules_to_db_writes_all_email_review_tables(initialized_user, db_session, tmp_path: Path) -> None:
    emails_path = tmp_path / "emails.jsonl"
    pred_path = tmp_path / "pred.jsonl"

    _write_jsonl(
        emails_path,
        [
            {
                "email_id": "email-1",
                "from": "instructor@school.edu",
                "subject": "[CSE 100] HW deadline extension",
                "date": "2026-03-01T10:00:00-08:00",
                "body_text": "Homework is moved to 2026-03-03T23:59:00-08:00. Submit by Gradescope.",
            }
        ],
    )
    _write_jsonl(
        pred_path,
        [
            {
                "email_id": "email-1",
                "label": "KEEP",
                "confidence": 0.91,
                "reasons": ["deadline detected"],
                "course_hints": ["CSE 100"],
                "event_type": "deadline",
                "action_items": [
                    {
                        "action": "Submit homework",
                        "due_iso": "2026-03-03T23:59:00-08:00",
                        "where": "Gradescope",
                    }
                ],
                "raw_extract": {
                    "deadline_text": "2026-03-03T23:59:00-08:00",
                    "time_text": "2026-03-03T23:59:00-08:00",
                    "location_text": "Gradescope",
                },
                "notes": None,
            }
        ],
    )

    stats_first = run_import(
        input_mbox=None,
        emails_jsonl=emails_path,
        pred_jsonl=pred_path,
        user_id=1,
        review_threshold=0.75,
        timezone_name="America/Los_Angeles",
        limit=None,
        dry_run=False,
    )
    assert stats_first["processed"] == 1
    assert stats_first["errors"] == 0

    assert db_session.scalar(select(func.count(EmailMessage.email_id))) == 1
    assert db_session.scalar(select(func.count(EmailRuleLabel.email_id))) == 1
    assert db_session.scalar(select(func.count(EmailActionItem.id))) == 1
    assert db_session.scalar(select(func.count(EmailRuleAnalysis.email_id))) == 1
    assert db_session.scalar(select(func.count(EmailRoute.email_id))) == 1

    stats_second = run_import(
        input_mbox=None,
        emails_jsonl=emails_path,
        pred_jsonl=pred_path,
        user_id=1,
        review_threshold=0.75,
        timezone_name="America/Los_Angeles",
        limit=None,
        dry_run=False,
    )
    assert stats_second["processed"] == 1
    assert stats_second["errors"] == 0
    assert db_session.scalar(select(func.count(EmailMessage.email_id))) == 1
    assert db_session.scalar(select(func.count(EmailRuleLabel.email_id))) == 1
    assert db_session.scalar(select(func.count(EmailActionItem.id))) == 1
    assert db_session.scalar(select(func.count(EmailRuleAnalysis.email_id))) == 1
    assert db_session.scalar(select(func.count(EmailRoute.email_id))) == 1


def test_import_rules_to_db_dry_run_does_not_write(initialized_user, db_session, tmp_path: Path) -> None:
    emails_path = tmp_path / "emails.jsonl"
    pred_path = tmp_path / "pred.jsonl"

    _write_jsonl(
        emails_path,
        [
            {
                "email_id": "email-dry-run",
                "from": "instructor@school.edu",
                "subject": "Reminder",
                "date": "2026-03-01T10:00:00-08:00",
                "body_text": "No action required.",
            }
        ],
    )
    _write_jsonl(
        pred_path,
        [
            {
                "email_id": "email-dry-run",
                "label": "DROP",
                "confidence": 0.8,
                "event_type": None,
                "reasons": ["non-actionable"],
                "course_hints": [],
                "action_items": [],
                "raw_extract": {"deadline_text": None, "time_text": None, "location_text": None},
                "notes": None,
            }
        ],
    )

    stats = run_import(
        input_mbox=None,
        emails_jsonl=emails_path,
        pred_jsonl=pred_path,
        user_id=1,
        review_threshold=0.75,
        timezone_name="America/Los_Angeles",
        limit=None,
        dry_run=True,
    )
    assert stats["dry_run"] is True
    assert stats["processed"] == 1
    assert db_session.scalar(select(func.count(EmailMessage.email_id))) == 0
