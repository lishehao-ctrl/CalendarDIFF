from __future__ import annotations

import argparse
import json

import scripts.run_agent_chain_trace_eval as chain_eval


def test_resolve_placeholders_replaces_full_value() -> None:
    snapshot = {"primary_change_id": 123, "missing_ticket_id": "missing-ticket-99"}
    assert chain_eval.resolve_placeholders("${primary_change_id}", snapshot) == 123
    assert chain_eval.resolve_placeholders("/tickets/${missing_ticket_id}", snapshot) == "/tickets/missing-ticket-99"


def test_select_sample_entries_filters_missing_placeholders() -> None:
    entries = [
        {"sample_id": "a", "kind": "command", "input_text": "ok", "scope_kind": "workspace"},
        {"sample_id": "b", "kind": "endpoint", "method": "GET", "path": "/agent/context/changes/${missing_change_id}"},
    ]
    snapshot = {"missing_change_id": 999}
    selected = chain_eval.select_sample_entries(entries=entries, workspace_snapshot=snapshot, sample_count=2, seed=1)
    assert len(selected) == 2


def test_build_command_step_rows_uses_scope_snapshot_and_raw_output_excerpt() -> None:
    command_snapshot = {
        "command_id": "cmd-1",
        "user_id": 12,
        "status": "completed",
        "plan_json": {
            "scope_snapshot": {"scope_kind": "workspace", "summary": {"pending": 2}},
            "steps": [
                {
                    "step_id": "step_1",
                    "title": "Get workspace",
                    "reason": "Need context",
                    "tool_name": "get_workspace_context",
                    "target_kind": "workspace",
                    "args": {},
                    "depends_on": [],
                    "risk_level": "low",
                    "execution_boundary": "read_only",
                }
            ],
        },
        "execution_results_json": {
            "results_by_step": {
                "step_1": {
                    "status": "succeeded",
                    "output_summary": {"status": "ok"},
                    "raw_output": {"summary": {"pending": 2}},
                    "error_text": None,
                    "started_at": "2026-03-27T00:00:01+00:00",
                    "finished_at": "2026-03-27T00:00:02+00:00",
                }
            }
        },
    }
    rows = chain_eval.build_command_step_rows(
        eval_run_id="eval-1",
        operation_id="op-1",
        sample_id="sample-1",
        operation_name="Workspace review",
        category="command_read",
        command_id="cmd-1",
        user_id=12,
        command_snapshot=command_snapshot,
        fallback_plan_payload={},
        fallback_execute_payload={},
    )
    assert len(rows) == 1
    assert rows[0].scope_kind == "workspace"
    assert json.loads(rows[0].raw_output_excerpt)["summary"]["pending"] == 2


def test_compute_summary_excludes_skipped_from_success_rate() -> None:
    operation_rows = [
        chain_eval.OperationTraceRow(
            eval_run_id="eval-1",
            operation_id="op-1",
            sample_id="sample-1",
            name="Command",
            kind="command",
            category="command_read",
            success=True,
            status="succeeded",
            note=None,
            command_id="cmd-1",
            command_status="completed",
            http_statuses=[201, 200],
            request_count=2,
            step_count=1,
            judged_step_count=0,
            operation_trace_score=None,
            judge_available=False,
            judge_notes=[],
            resolved_entry={},
            http_trace_excerpts=[],
        ),
        chain_eval.OperationTraceRow(
            eval_run_id="eval-1",
            operation_id="op-2",
            sample_id="sample-2",
            name="Skipped",
            kind="command",
            category="command_read",
            success=False,
            status="skipped",
            note="unsupported",
            command_id="cmd-2",
            command_status="unsupported",
            http_statuses=[201],
            request_count=1,
            step_count=0,
            judged_step_count=0,
            operation_trace_score=None,
            judge_available=False,
            judge_notes=[],
            resolved_entry={},
            http_trace_excerpts=[],
        ),
    ]
    summary = chain_eval.compute_summary(
        operation_rows=operation_rows,
        step_rows=[],
        sample_plan={"seed": 1, "sample_count": 2, "success_threshold": 0.8, "judge_mode": "off"},
    )
    assert summary["success_rate"] == 1.0
    assert summary["skipped_operation_count"] == 1


def test_run_and_report_writes_artifacts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(chain_eval.replay, "build_api_client", lambda public_api_base, api_key: object())
    monkeypatch.setattr(
        chain_eval.replay,
        "ensure_authenticated_session",
        lambda client, email, password: {"id": 12, "email": email},
    )
    monkeypatch.setattr(chain_eval, "load_workspace_snapshot", lambda client, user, run_dir, started_at: {"primary_change_id": 1})
    monkeypatch.setattr(
        chain_eval,
        "load_corpus_entries",
        lambda path: [
            {
                "sample_id": "ep.workspace.context",
                "kind": "endpoint",
                "name": "Workspace",
                "category": "endpoint_read",
                "method": "GET",
                "path": "/agent/context/workspace",
                "body": None,
                "expected_statuses": [200],
            }
        ],
    )
    monkeypatch.setattr(
        chain_eval,
        "request_json",
        lambda client, method, path, json_body, expected_statuses: (
            200,
            {"ok": True},
            {
                "method": method,
                "path": path,
                "status": 200,
                "expected_statuses": expected_statuses,
                "elapsed_ms": 1.0,
                "request_excerpt": "{}",
                "response_excerpt": "{\"ok\":true}",
                "recorded_at": "2026-03-27T00:00:00+00:00",
            },
        ),
    )

    args = argparse.Namespace(
        command="run",
        public_api_base="http://example.test",
        api_key="test-key",
        email="trace@example.com",
        password="password123",
        sample_count=1,
        seed=1,
        success_threshold=0.8,
        judge_mode="off",
        corpus_path=str(tmp_path / "corpus.json"),
        output_root=str(tmp_path),
    )
    run_dir = chain_eval.run_eval(args)

    assert (run_dir / chain_eval.SAMPLE_PLAN_FILE).exists()
    assert (run_dir / chain_eval.TRACE_ROWS_FILE).exists()
    assert (run_dir / chain_eval.SUMMARY_JSON_FILE).exists()
    summary = chain_eval.report_eval(run_dir)
    assert summary["overall_status"] == "passed"
