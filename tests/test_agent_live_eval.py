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
            "baseline_change_id": None,
            "reviewed_change_id": None,
            "executable_source_id": 21,
            "selected_source_id": 21,
            "disconnected_gmail_source_id": None,
            "family_relink_raw_type_id": None,
            "family_relink_drift_raw_type_id": None,
            "family_relink_target_family_id": None,
            "label_learning_change_id": None,
            "label_learning_drift_change_id": None,
            "label_learning_family_id": None,
            "missing_change_id": 999001,
            "missing_source_id": 999002,
            "missing_proposal_id": 999003,
            "missing_ticket_id": "missing-ticket-1000",
        }
    )

    by_id = {row.scenario_id: row for row in plan}
    assert len(plan) == 38
    assert by_id["change.context.primary"].enabled is True
    assert by_id["change.proposal.repeat"].enabled is False
    assert by_id["change.ticket.cancel"].enabled is False
    assert by_id["change.ticket.drift-confirm"].enabled is False
    assert by_id["change.edit-proposal.create"].enabled is False
    assert by_id["family.relink-commit.proposal"].enabled is False
    assert by_id["label-learning.commit.proposal"].enabled is False
    assert by_id["source.context.disconnected-gmail"].enabled is False
    assert by_id["source.proposal.create-nonexec"].enabled is False
    assert by_id["change.proposal.missing-fetch"].metadata["target_id"] == 999003
    assert by_id["ticket.missing-get"].metadata["target_id"] == "missing-ticket-1000"


def test_build_full_scenarios_adds_mcp_matrix() -> None:
    plan = live_eval.build_full_scenarios(
        {
            "primary_change_id": 11,
            "repeat_change_id": 12,
            "cancel_change_id": 13,
            "drift_change_id": 14,
            "baseline_change_id": 16,
            "reviewed_change_id": 15,
            "executable_source_id": 21,
            "selected_source_id": 21,
            "disconnected_gmail_source_id": 22,
            "family_relink_raw_type_id": 31,
            "family_relink_drift_raw_type_id": 32,
            "family_relink_target_family_id": 41,
            "label_learning_change_id": 51,
            "label_learning_drift_change_id": 52,
            "label_learning_family_id": 61,
            "label_learning_drift_family_id": 62,
            "missing_change_id": 999001,
            "missing_source_id": 999002,
            "missing_proposal_id": 999003,
            "missing_ticket_id": "missing-ticket-1000",
            "cross_user_email": "other@example.com",
        }
    )

    by_id = {row.scenario_id: row for row in plan}
    assert len(plan) == 48
    assert by_id["mcp.token.create"].enabled is True
    assert by_id["mcp.impl.workspace-scoped"].enabled is True
    assert by_id["mcp.impl.workspace-scoped"].metadata["cross_user_email"] == "other@example.com"
    assert by_id["mcp.impl.change-proposal"].metadata["target_id"] == 12
    assert by_id["mcp.auth.verify-revoked"].enabled is True
    assert by_id["family.relink-commit.proposal"].metadata["raw_type_id"] == 31
    assert by_id["label-learning.commit.proposal"].metadata["family_id"] == 61


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
    assert summary["reliability"]["context_read_success_rate"] is None
    assert summary["reliability"]["state_drift_guard_success_rate"] is None
    assert summary["token_usage"]["overall"]["total_tokens"] == 0
    assert summary["cost_usd"]["overall"]["estimated_cost_usd"] == 0.0
    assert summary["safety"]["corrupt_success_count"] == 1
    assert summary["safety"]["procedural_integrity_score"] == 0.5
    assert summary["scenario_weighted_score"] == 0.425
    assert summary["reliability"]["proposal_success_rate"] == 1.0
    assert summary["reliability"]["ticket_create_success_rate"] is None
    assert summary["executable_actions_exercised"]["change_decision"] is False
    assert "corrupt_success_detected" in summary["threshold_failures"]


def test_evaluate_repeat_proposal_outcome_accepts_deduped_open_proposal() -> None:
    outcome = live_eval.evaluate_repeat_proposal_outcome(
        first_status=201,
        first_payload={"proposal_id": 42},
        second_status=201,
        second_payload={"proposal_id": 42},
        fetched_ok=True,
    )

    assert outcome["success"] is True
    assert outcome["details"]["deduped_open_proposal"] is True
    assert outcome["details"]["returned_distinct_rows"] is False


def test_compute_summary_counts_repeat_proposal_dedupe_as_single_persisted_row() -> None:
    plan = [
        live_eval.ScenarioSpec("change.proposal.repeat", "Repeat proposal", "change_proposal", "change_proposal_repeat"),
    ]
    results = [
        live_eval.ScenarioResult(
            scenario_id="change.proposal.repeat",
            name="Repeat proposal",
            category="change_proposal",
            operation="change_proposal_repeat",
            status="passed",
            success=True,
            expected_statuses=[201],
            http_status=201,
            started_at="2026-03-23T00:00:00+00:00",
            finished_at="2026-03-23T00:00:01+00:00",
            elapsed_ms=100.0,
            note="deduped",
            details={
                "deduped_open_proposal": True,
                "returned_distinct_rows": False,
                "fetched_ok": True,
                "first_proposal_id": 7,
                "second_proposal_id": 7,
            },
        ),
    ]

    summary = live_eval.compute_summary(
        plan=plan,
        results=results,
        proposal_audit={"count": 1},
        ticket_audit={"count": 0},
    )

    assert summary["audit"]["proposal_rows"] == 1
    assert summary["audit"]["proposal_persistence_completeness"] == 1.0


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
    assert saved_summary["token_usage"]["overall"]["total_tokens"] == 0
    markdown = (run_dir / live_eval.SUMMARY_FILE).read_text(encoding="utf-8")
    assert "Agent Live Eval Summary" in markdown
    assert "Token & Cost" in markdown
    assert "Workspace context primary read" not in markdown
