from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.db.models.review import ChangeIntakePhase, ChangeType
from app.modules.changes.decision_support import build_change_decision_support


def _change(*, change_type: ChangeType, intake_phase: ChangeIntakePhase = ChangeIntakePhase.REPLAY, before: dict | None = None, after: dict | None = None):
    return SimpleNamespace(
        change_type=change_type,
        intake_phase=intake_phase,
        before_semantic_json=before,
        after_semantic_json=after,
        detected_at=datetime.now(timezone.utc),
    )


def test_removed_change_exposes_codes_and_key_fact_items() -> None:
    support = build_change_decision_support(
        change=_change(
            change_type=ChangeType.REMOVED,
            before={
                "course_dept": "CSE",
                "course_number": 100,
                "event_name": "RQ19",
                "due_date": "2026-02-20",
                "due_time": "16:00:00",
                "time_precision": "datetime",
            },
        ),
        primary_source={"provider": "ics"},
        change_summary={"old": {"value_time": "2026-02-20T16:00:00Z"}, "new": {}},
    )
    assert support["why_now_code"] == "changes.removed.why_now"
    assert support["suggested_action_reason_code"] == "changes.removed.suggested_action_reason"
    assert support["risk_summary_code"] == "changes.removed.risk_summary"
    assert support["outcome_preview_codes"]["approve"] == "changes.removed.outcome.approve"
    assert any(item["code"] == "course" for item in support["key_fact_items"])
    assert any(item["code"] == "primary_source" and item["value"] == "Canvas ICS" for item in support["key_fact_items"])


def test_created_baseline_change_exposes_baseline_codes() -> None:
    support = build_change_decision_support(
        change=_change(
            change_type=ChangeType.CREATED,
            intake_phase=ChangeIntakePhase.BASELINE,
            after={
                "course_dept": "CSE",
                "course_number": 8,
                "family_name": "Homework",
                "ordinal": 1,
                "due_date": "2026-03-15",
                "time_precision": "date_only",
            },
        ),
        primary_source={"provider": "gmail"},
        change_summary={"new": {"value_time": "2026-03-15T00:00:00Z"}},
    )
    assert support["why_now_code"] == "changes.baseline_created.why_now"
    assert support["suggested_action_reason_code"] == "changes.baseline_created.suggested_action_reason"
    assert support["risk_summary_code"] == "changes.baseline_created.risk_summary"
    assert support["outcome_preview_codes"]["approve"] == "changes.baseline_created.outcome.approve"
    assert any(item["code"] == "proposed_time" and item["value"] == "2026-03-15" for item in support["key_fact_items"])
