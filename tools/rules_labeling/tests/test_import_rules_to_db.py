from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db.models import User
from tools.rules_labeling import import_rules_to_db


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class _FakeSession:
    def __init__(self) -> None:
        self.user = User(id=1, email=None, notify_email="student@example.com")
        self.commit_called = False
        self.rollback_called = False
        self.close_called = False

    def get(self, model, key):  # noqa: ANN001
        if model is User and key == 1:
            return self.user
        return None

    def close(self) -> None:
        self.close_called = True

    def rollback(self) -> None:
        self.rollback_called = True

    def commit(self) -> None:
        self.commit_called = True


def test_run_import_dry_run_jsonl_pred(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    emails_path = tmp_path / "emails.jsonl"
    pred_path = tmp_path / "pred.jsonl"
    _write_jsonl(
        emails_path,
        [
            {
                "email_id": "email-1",
                "from": "staff@school.edu",
                "subject": "Deadline moved",
                "date": "2026-03-01T10:00:00-08:00",
                "body_text": "Homework moved to 2026-03-03T23:59:00-08:00.",
            }
        ],
    )
    _write_jsonl(
        pred_path,
        [
            {
                "email_id": "email-1",
                "label": "KEEP",
                "confidence": 0.9,
                "event_type": "deadline",
                "reasons": ["deadline detected"],
                "course_hints": ["CSE 100"],
                "action_items": [],
                "raw_extract": {"deadline_text": "2026-03-03T23:59:00-08:00", "time_text": None, "location_text": None},
                "notes": None,
            }
        ],
    )

    fake_session = _FakeSession()
    monkeypatch.setattr(import_rules_to_db, "get_session_factory", lambda: (lambda: fake_session))

    stats = import_rules_to_db.run_import(
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
    assert stats["errors"] == 0
    assert fake_session.rollback_called is True
    assert fake_session.commit_called is False
    assert fake_session.close_called is True


def test_run_import_requires_matching_input_modes(tmp_path: Path) -> None:
    emails_path = tmp_path / "emails.jsonl"
    _write_jsonl(emails_path, [])

    with pytest.raises(RuntimeError):
        import_rules_to_db.run_import(
            input_mbox=None,
            emails_jsonl=emails_path,
            pred_jsonl=None,
            user_id=1,
            review_threshold=0.75,
            timezone_name="America/Los_Angeles",
            limit=None,
            dry_run=True,
        )
