from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import scripts.run_agent_live_eval as live_eval
import scripts.run_agent_trace_eval as trace_eval
from app.modules.llm_gateway.contracts import LlmInvokeResult


def _write_live_eval_fixture(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / live_eval.SCENARIO_PLAN_FILE).write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario_id": "workspace.context.primary",
                        "name": "Workspace context primary read",
                        "category": "workspace_context",
                        "operation": "workspace_context",
                        "enabled": True,
                        "skip_reason": None,
                        "metadata": {"target_kind": "workspace"},
                    },
                    {
                        "scenario_id": "mcp.impl.workspace-scoped",
                        "name": "MCP workspace implementation",
                        "category": "mcp_impl",
                        "operation": "mcp_workspace_context",
                        "enabled": True,
                        "skip_reason": None,
                        "metadata": {"target_kind": "workspace"},
                    },
                    {
                        "scenario_id": "ctx.skip",
                        "name": "Skipped scenario",
                        "category": "workspace_context",
                        "operation": "workspace_context",
                        "enabled": False,
                        "skip_reason": "disabled",
                        "metadata": {},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    live_eval.append_jsonl(
        run_dir / live_eval.SCENARIO_RESULTS_FILE,
        {
            "scenario_id": "workspace.context.primary",
            "name": "Workspace context primary read",
            "category": "workspace_context",
            "operation": "workspace_context",
            "status": "passed",
            "success": True,
            "expected_statuses": [200],
            "http_status": 200,
            "started_at": "2026-03-27T00:00:00+00:00",
            "finished_at": "2026-03-27T00:00:01+00:00",
            "elapsed_ms": 120.0,
            "note": None,
            "details": {"llm_usage": {"total_tokens": 0}},
        },
    )
    live_eval.append_jsonl(
        run_dir / live_eval.SCENARIO_RESULTS_FILE,
        {
            "scenario_id": "mcp.impl.workspace-scoped",
            "name": "MCP workspace implementation",
            "category": "mcp_impl",
            "operation": "mcp_workspace_context",
            "status": "failed",
            "success": False,
            "expected_statuses": [200],
            "http_status": 500,
            "started_at": "2026-03-27T00:00:02+00:00",
            "finished_at": "2026-03-27T00:00:03+00:00",
            "elapsed_ms": 320.0,
            "note": "upstream failed",
            "details": {"error_code": "trace_eval_demo"},
        },
    )
    live_eval.append_jsonl(
        run_dir / live_eval.SCENARIO_RESULTS_FILE,
        {
            "scenario_id": "ctx.skip",
            "name": "Skipped scenario",
            "category": "workspace_context",
            "operation": "workspace_context",
            "status": "skipped",
            "success": True,
            "expected_statuses": None,
            "http_status": None,
            "started_at": "2026-03-27T00:00:04+00:00",
            "finished_at": "2026-03-27T00:00:04+00:00",
            "elapsed_ms": 0.0,
            "note": "disabled",
            "details": None,
        },
    )
    live_eval.append_jsonl(
        run_dir / live_eval.API_TRACE_FILE,
        {
            "scenario_id": "workspace.context.primary",
            "method": "GET",
            "path": "/agent/context/workspace",
            "status": 200,
            "expected_statuses": [200],
            "elapsed_ms": 55.0,
            "request_json": {},
            "response_excerpt": "{\"summary\": {\"changes_pending\": 2}}",
            "recorded_at": "2026-03-27T00:00:00+00:00",
        },
    )
    live_eval.append_jsonl(
        run_dir / live_eval.MCP_TRACE_FILE,
        {
            "scenario_id": "mcp.impl.workspace-scoped",
            "action": "get_workspace_context",
            "success": False,
            "elapsed_ms": 88.0,
            "request": {"scope": "workspace"},
            "response_excerpt": None,
            "error": "transport failed",
            "recorded_at": "2026-03-27T00:00:02+00:00",
        },
    )
    (run_dir / live_eval.PROPOSAL_AUDIT_FILE).write_text(json.dumps({"count": 1}), encoding="utf-8")
    (run_dir / live_eval.TICKET_AUDIT_FILE).write_text(json.dumps({"count": 0}), encoding="utf-8")
    (run_dir / live_eval.LLM_USAGE_AUDIT_FILE).write_text(
        json.dumps({"token_usage": {"overall": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}, "cost_usd": {"overall": {"estimated_cost_usd": 0.0}}}),
        encoding="utf-8",
    )
    (run_dir / live_eval.SUMMARY_JSON_FILE).write_text(
        json.dumps(
            {
                "generated_at": "2026-03-27T00:01:00+00:00",
                "scenario_count": 3,
                "executed_count": 2,
                "passed_count": 1,
                "failed_count": 1,
                "skipped_count": 1,
                "success_rate": 0.5,
                "scenario_weighted_score": 0.4,
            }
        ),
        encoding="utf-8",
    )


def test_load_trace_bundles_groups_api_and_mcp_rows(tmp_path: Path) -> None:
    live_eval_dir = tmp_path / "agent-live-eval-fixture"
    _write_live_eval_fixture(live_eval_dir)

    bundles = trace_eval.load_trace_bundles(live_eval_run_dir=live_eval_dir)
    by_id = {row.scenario_id: row for row in bundles}

    assert len(bundles) == 3
    assert by_id["workspace.context.primary"].status == "passed"
    assert len(by_id["workspace.context.primary"].api_trace_excerpts) == 1
    assert by_id["workspace.context.primary"].api_trace_excerpts[0]["path"] == "/agent/context/workspace"
    assert len(by_id["mcp.impl.workspace-scoped"].mcp_trace_excerpts) == 1
    assert by_id["ctx.skip"].status == "skipped"


def test_judge_trace_bundle_off_keeps_row_non_judged() -> None:
    bundle = trace_eval.ScenarioTraceBundle(
        scenario_id="workspace.context.primary",
        name="Workspace context primary read",
        category="workspace_context",
        operation="workspace_context",
        metadata={},
        status="passed",
        success=True,
        expected_statuses=[200],
        http_status=200,
        note=None,
        details=None,
        api_trace_excerpts=[{"kind": "api", "path": "/agent/context/workspace"}],
        mcp_trace_excerpts=[],
    )

    row = trace_eval.judge_trace_bundle(bundle=bundle, judge_mode="off")

    assert row.judge_available is False
    assert row.scenario_trace_score is None
    assert row.judge_notes == []


def test_judge_trace_bundle_llm_success_scores_and_cost(monkeypatch) -> None:
    bundle = trace_eval.ScenarioTraceBundle(
        scenario_id="workspace.context.primary",
        name="Workspace context primary read",
        category="workspace_context",
        operation="workspace_context",
        metadata={},
        status="passed",
        success=True,
        expected_statuses=[200],
        http_status=200,
        note=None,
        details=None,
        api_trace_excerpts=[{"kind": "api", "path": "/agent/context/workspace"}],
        mcp_trace_excerpts=[],
    )

    def _fake_invoke(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args
        invoke_request = kwargs["invoke_request"]
        assert invoke_request.profile_family == "judge"
        return LlmInvokeResult(
            json_object={
                "task_completion_alignment_score": 0.9,
                "boundedness_score": 1.0,
                "efficiency_score": 0.8,
                "operator_clarity_score": 0.7,
                "notes": ["clear trace"],
            },
            provider_id="env-default",
            protocol="responses",
            model="qwen3.5-flash",
            latency_ms=10,
            vendor="dashscope_openai",
            raw_usage={"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10, "total_tokens": 110},
        )

    monkeypatch.setattr(trace_eval, "invoke_llm_json", _fake_invoke)

    row = trace_eval.judge_trace_bundle(bundle=bundle, judge_mode="llm")

    assert row.judge_available is True
    assert row.scenario_trace_score == 0.85
    assert row.judge_notes == ["clear trace"]
    assert row.judge_usage == {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10, "total_tokens": 110}
    assert isinstance(row.judge_cost, dict)


def test_judge_trace_bundle_llm_failure_falls_back(monkeypatch) -> None:
    bundle = trace_eval.ScenarioTraceBundle(
        scenario_id="mcp.impl.workspace-scoped",
        name="MCP workspace implementation",
        category="mcp_impl",
        operation="mcp_workspace_context",
        metadata={},
        status="failed",
        success=False,
        expected_statuses=[200],
        http_status=500,
        note="failed",
        details=None,
        api_trace_excerpts=[],
        mcp_trace_excerpts=[{"kind": "mcp", "action": "get_workspace_context"}],
    )

    monkeypatch.setattr(trace_eval, "invoke_llm_json", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    row = trace_eval.judge_trace_bundle(bundle=bundle, judge_mode="llm")

    assert row.judge_available is False
    assert row.scenario_trace_score is None


def test_compute_summary_follows_source_live_eval_status_and_aggregates_scores() -> None:
    rows = [
        trace_eval.ScenarioTraceJudgeRow(
            scenario_id="a",
            name="A",
            category="workspace_context",
            operation="workspace_context",
            metadata={},
            status="passed",
            success=True,
            expected_statuses=[200],
            http_status=200,
            note=None,
            details=None,
            api_trace_excerpts=[],
            mcp_trace_excerpts=[],
            judge_available=True,
            task_completion_alignment_score=0.9,
            boundedness_score=1.0,
            efficiency_score=0.8,
            operator_clarity_score=0.7,
            scenario_trace_score=0.85,
            judge_notes=["good"],
            judge_usage={"input_tokens": 50, "cached_input_tokens": 0, "output_tokens": 5, "total_tokens": 55},
            judge_cost={"estimated_cost_usd": 0.00001, "input_cost_usd": 0.0, "cached_input_cost_usd": 0.0, "output_cost_usd": 0.00001, "pricing_available": True, "unpriced_call_count": 0},
        ),
        trace_eval.ScenarioTraceJudgeRow(
            scenario_id="b",
            name="B",
            category="mcp_impl",
            operation="mcp_workspace_context",
            metadata={},
            status="failed",
            success=False,
            expected_statuses=[200],
            http_status=500,
            note="failed",
            details=None,
            api_trace_excerpts=[],
            mcp_trace_excerpts=[],
            judge_available=True,
            task_completion_alignment_score=0.4,
            boundedness_score=0.9,
            efficiency_score=0.3,
            operator_clarity_score=0.4,
            scenario_trace_score=0.5,
            judge_notes=["wasteful"],
            judge_usage={"input_tokens": 70, "cached_input_tokens": 0, "output_tokens": 7, "total_tokens": 77},
            judge_cost={"estimated_cost_usd": 0.00002, "input_cost_usd": 0.0, "cached_input_cost_usd": 0.0, "output_cost_usd": 0.00002, "pricing_available": True, "unpriced_call_count": 0},
        ),
        trace_eval.ScenarioTraceJudgeRow(
            scenario_id="skip",
            name="Skip",
            category="workspace_context",
            operation="workspace_context",
            metadata={},
            status="skipped",
            success=True,
            expected_statuses=None,
            http_status=None,
            note="disabled",
            details=None,
            api_trace_excerpts=[],
            mcp_trace_excerpts=[],
            judge_available=False,
            task_completion_alignment_score=None,
            boundedness_score=None,
            efficiency_score=None,
            operator_clarity_score=None,
            scenario_trace_score=None,
            judge_notes=[],
            judge_usage=None,
            judge_cost=None,
        ),
    ]

    summary = trace_eval.compute_summary(
        rows=rows,
        source_live_eval_summary={"success_rate": 1.0, "failed_count": 0, "executed_count": 2, "passed_count": 2, "scenario_weighted_score": 0.9},
        judge_mode="llm",
    )

    assert summary["overall_status"] == "passed"
    assert summary["judge_available_rate"] == 1.0
    assert summary["scenario_trace_score_avg"] == 0.675
    assert summary["low_trace_score_count"] == 1
    assert summary["judge_token_usage"]["overall"]["total_tokens"] == 132
    assert summary["trace_quality_summary"]["lowest_scenarios"][0]["scenario_id"] == "b"
    assert "good" in summary["trace_quality_summary"]["representative_notes"]


def test_run_and_report_trace_eval_with_existing_live_eval_dir(tmp_path: Path) -> None:
    live_eval_dir = tmp_path / "agent-live-eval-fixture"
    _write_live_eval_fixture(live_eval_dir)

    args = argparse.Namespace(
        command="run",
        live_eval_run_dir=str(live_eval_dir),
        public_api_base=None,
        api_key=None,
        email=None,
        password=None,
        scenario_set="core",
        cross_user_email=None,
        output_root=str(tmp_path),
        judge_mode="off",
    )

    run_dir = trace_eval.run_eval(args)

    assert (run_dir / trace_eval.ROWS_FILE).exists()
    assert (run_dir / trace_eval.SUMMARY_JSON_FILE).exists()
    assert (run_dir / trace_eval.SUMMARY_MD_FILE).exists()
    assert (run_dir / trace_eval.LIVE_EVAL_RUN_DIR_FILE).read_text(encoding="utf-8").strip() == str(live_eval_dir.resolve())

    summary = trace_eval.report_eval(run_dir)

    assert summary["source_live_eval_summary"]["executed_count"] == 2
    assert summary["overall_status"] == "failed"
