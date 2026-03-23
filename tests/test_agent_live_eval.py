from __future__ import annotations

import json
from pathlib import Path

import scripts.run_agent_live_eval as live_eval


def test_build_core_scenarios_marks_missing_targets_as_skipped() -> None:
    plan = live_eval.build_core_scenarios(
        {
            "primary_change_id": None,
            "selected_change_id": None,
            "executable_source_id": None,
            "selected_source_id": None,
            "missing_change_id": 999001,
            "missing_source_id": 999002,
        }
    )

    by_id = {row.scenario_id: row for row in plan}
    assert by_id["change.context.primary"].enabled is False
    assert by_id["change.context.primary"].skip_reason == "no pending change discovered during preflight"
    assert by_id["source.context.primary"].enabled is False
    assert by_id["source.context.primary"].skip_reason == "no source discovered during preflight"
    assert by_id["change.context.missing"].metadata["target_id"] == 999001
    assert by_id["source.context.missing"].metadata["target_id"] == 999002


def test_build_expanded_scenarios_marks_optional_targets_as_skipped() -> None:
    plan = live_eval.build_expanded_scenarios(
        {
            "primary_change_id": 11,
            "repeat_change_id": None,
            "cancel_change_id": None,
            "drift_change_id": None,
            "reviewed_change_id": None,
            "executable_source_id": 21,
            "selected_source_id": 21,
            "disconnected_gmail_source_id": None,
            "missing_change_id": 999001,
            "missing_source_id": 999002,
            "missing_proposal_id": 999003,
            "missing_ticket_id": "missing-ticket-1000",
        }
    )

    by_id = {row.scenario_id: row for row in plan}
    assert len(plan) == 26
    assert by_id["change.context.primary"].enabled is True
    assert by_id["change.proposal.repeat"].enabled is False
    assert by_id["change.ticket.cancel"].enabled is False
    assert by_id["change.ticket.drift-confirm"].enabled is False
    assert by_id["source.context.disconnected-gmail"].enabled is False
    assert by_id["source.proposal.create-nonexec"].enabled is False
    assert by_id["change.proposal.missing-fetch"].metadata["target_id"] == 999003
    assert by_id["ticket.missing-get"].metadata["target_id"] == "missing-ticket-1000"


def test_compute_summary_counts_failures_and_guard_violations() -> None:
    plan = [
        live_eval.ScenarioSpec("proposal.ok", "Proposal ok", "change_proposal", "change_proposal_create"),
        live_eval.ScenarioSpec("ticket.guard", "Source guard", "source_ticket", "source_ticket_guard_or_create"),
        live_eval.ScenarioSpec("ctx.skip", "Skipped", "workspace_context", "workspace_context"),
    ]
    results = [
        live_eval.ScenarioResult(
            scenario_id="proposal.ok",
            name="Proposal ok",
            category="change_proposal",
            operation="change_proposal_create",
            status="passed",
            success=True,
            expected_statuses=[201],
            http_status=201,
            started_at="2026-03-23T00:00:00+00:00",
            finished_at="2026-03-23T00:00:01+00:00",
            elapsed_ms=120.0,
        ),
        live_eval.ScenarioResult(
            scenario_id="ticket.guard",
            name="Source guard",
            category="source_ticket",
            operation="source_ticket_guard_or_create",
            status="failed",
            success=False,
            expected_statuses=[409],
            http_status=201,
            started_at="2026-03-23T00:00:02+00:00",
            finished_at="2026-03-23T00:00:03+00:00",
            elapsed_ms=240.0,
            note="non-executable source proposal incorrectly created a ticket",
        ),
        live_eval.ScenarioResult(
            scenario_id="ctx.skip",
            name="Skipped",
            category="workspace_context",
            operation="workspace_context",
            status="skipped",
            success=True,
            expected_statuses=None,
            http_status=None,
            started_at="2026-03-23T00:00:04+00:00",
            finished_at="2026-03-23T00:00:04+00:00",
            elapsed_ms=0.0,
            note="not available",
        ),
    ]

    summary = live_eval.compute_summary(
        plan=plan,
        results=results,
        proposal_audit={"count": 1},
        ticket_audit={"count": 1},
    )

    assert summary["executed_count"] == 2
    assert summary["passed_count"] == 1
    assert summary["failed_count"] == 1
    assert summary["skipped_count"] == 1
    assert summary["safety"]["non_executable_proposal_ticket_created_count"] == 1
    assert "non_executable_proposal_ticket_created" in summary["threshold_failures"]
    assert summary["latency_ms"]["overall"]["p50"] == 180.0
    assert summary["reliability"]["proposal_success_rate"] == 1.0
    assert summary["reliability"]["ticket_create_success_rate"] is None


def test_report_eval_rebuilds_summary_from_saved_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "eval-run"
    run_dir.mkdir()
    plan = {
        "scenarios": [
            {
                "scenario_id": "workspace.context.primary",
                "name": "Workspace context primary read",
                "category": "workspace_context",
                "operation": "workspace_context",
                "enabled": True,
                "skip_reason": None,
                "metadata": {},
            }
        ]
    }
    (run_dir / live_eval.SCENARIO_PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
    (run_dir / live_eval.SCENARIO_RESULTS_FILE).write_text(
        json.dumps(
            {
                "scenario_id": "workspace.context.primary",
                "name": "Workspace context primary read",
                "category": "workspace_context",
                "operation": "workspace_context",
                "status": "passed",
                "success": True,
                "expected_statuses": [200],
                "http_status": 200,
                "started_at": "2026-03-23T00:00:00+00:00",
                "finished_at": "2026-03-23T00:00:01+00:00",
                "elapsed_ms": 111.0,
                "target_kind": None,
                "target_id": None,
                "note": "workspace context loaded",
                "error_code": None,
                "response_excerpt": "{\"ok\":true}",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / live_eval.PROPOSAL_AUDIT_FILE).write_text(json.dumps({"count": 0, "items": []}), encoding="utf-8")
    (run_dir / live_eval.TICKET_AUDIT_FILE).write_text(json.dumps({"count": 0, "items": []}), encoding="utf-8")

    summary = live_eval.report_eval(run_dir)

    assert summary["scenario_count"] == 1
    assert summary["executed_count"] == 1
    assert summary["passed_count"] == 1
    assert (run_dir / live_eval.SUMMARY_JSON_FILE).exists()
    assert (run_dir / live_eval.SUMMARY_FILE).exists()
    saved_summary = json.loads((run_dir / live_eval.SUMMARY_JSON_FILE).read_text(encoding="utf-8"))
    assert saved_summary["passed_count"] == 1
    markdown = (run_dir / live_eval.SUMMARY_FILE).read_text(encoding="utf-8")
    assert "Agent Live Eval Summary" in markdown
    assert "Workspace context primary read" not in markdown
