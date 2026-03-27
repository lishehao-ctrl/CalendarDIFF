from __future__ import annotations

from datetime import UTC, datetime

import scripts.run_agent_claw_strict_eval as closeout


def test_summarize_dirty_categories_marks_expected_groups() -> None:
    payload = "\n".join(
        [
            " M frontend/components/overview-page-client.tsx",
            " M app/modules/llm_gateway/gateway.py",
            " M app/modules/sources/sources_router.py",
            " M contracts/openapi/public-service.json",
        ]
    )

    summary = closeout.summarize_dirty_categories(payload)

    assert summary["excluded_categories"] == {
        "frontend": True,
        "llm_gateway": True,
        "sources": True,
        "openapi_snapshot": True,
    }


def test_build_final_report_marks_success_when_all_layers_pass() -> None:
    report = closeout.build_final_report(
        started_at=datetime.now(UTC),
        excluded_dirty={"raw_paths": [], "excluded_categories": {"frontend": False, "llm_gateway": False, "sources": False, "openapi_snapshot": False}},
        strict_results=[{"success": True}],
        pycompile_result={"success": True},
        live_eval_summary={
            "success_rate": 1.0,
            "scenario_weighted_score": 0.96,
            "safety": {"procedural_integrity_score": 1.0},
            "cost_usd": {"overall": {"estimated_cost_usd": 0.004}},
            "executable_actions_exercised": {
                "change_decision": True,
                "proposal_edit_commit": True,
                "run_source_sync": True,
                "family_relink_commit": True,
                "label_learning_add_alias_commit": True,
            },
        },
        proposal_quality_summary={"overall_quality_score_avg": 0.92},
        real_user_flow_summary={"overall_status": "passed", "goal_completion_rate": 0.8, "passed_flow_count": 4, "flow_count": 5},
        claw_smoke_summary={
            "success": True,
            "steps": [
                {"name": "recent_activity_before", "ok": True, "payload": {}},
                {"name": "workspace_context", "ok": True, "payload": {}},
                {"name": "change_context", "ok": True, "payload": {}},
                {"name": "family_context", "ok": True, "payload": {}},
                {"name": "change_proposal", "ok": True, "payload": {}},
                {"name": "change_edit_commit_proposal", "ok": True, "payload": {}},
                {"name": "change_edit_commit_ticket_create", "ok": True, "payload": {}},
                {"name": "change_edit_commit_ticket_confirm", "ok": True, "payload": {}},
                {"name": "family_relink_commit_proposal", "ok": True, "payload": {}},
                {"name": "family_relink_commit_ticket_create", "ok": True, "payload": {}},
                {"name": "family_relink_commit_ticket_confirm", "ok": True, "payload": {}},
                {"name": "family_relink_preview", "ok": True, "payload": {"can_create_ticket": False}},
                {"name": "approval_ticket_create", "ok": True, "payload": {}},
                {"name": "approval_ticket_confirm", "ok": True, "payload": {}},
                {"name": "settings_mcp_invocations", "ok": True, "payload": {"latest_tool_names": ["get_workspace_context"]}},
            ],
        },
        db_audit={"mcp_invocation_count": 4, "proposal_ticket_correlation_success": True, "latest_tool_names": ["get_workspace_context"]},
        live_llm_error=None,
    )

    assert report["success"] is True
    assert report["passed"] is True
    assert report["layers"]["real_user_flow"] is True
    assert report["tool_families_exercised"]["read_context"] is True
    assert report["tool_families_exercised"]["proposal"] is True
    assert report["tool_families_exercised"]["approval"] is True
    assert report["smoke_actions_exercised"]["proposal_edit_commit"] is True
    assert report["smoke_actions_exercised"]["family_low_risk_execute"] is True
    assert report["executable_actions_exercised"]["label_learning_add_alias_commit"] is True
    assert report["family_relink_preview_non_executable"] is True
    assert report["agent_execution_score"] == 0.96
    assert report["agent_quality_score"] == 0.92
    assert report["agent_safety_score"] == 1.0
    assert report["agent_cost_efficiency_score"] == 1.0
    assert report["agent_goal_completion_score"] == 0.8
    assert report["overall_agent_score"] == 0.944


def test_build_final_report_marks_failure_when_live_llm_env_missing() -> None:
    report = closeout.build_final_report(
        started_at=datetime.now(UTC),
        excluded_dirty={"raw_paths": [], "excluded_categories": {"frontend": False, "llm_gateway": False, "sources": False, "openapi_snapshot": False}},
        strict_results=[{"success": True}],
        pycompile_result={"success": True},
        live_eval_summary={"success_rate": 0.0, "scenario_weighted_score": 0.0, "safety": {"procedural_integrity_score": 0.0}, "cost_usd": {"overall": {"estimated_cost_usd": 0.0}}, "executable_actions_exercised": {}},
        proposal_quality_summary=None,
        real_user_flow_summary=None,
        claw_smoke_summary=None,
        db_audit=None,
        live_llm_error="live LLM env not configured: LLM_BASE_URL is not configured",
    )

    assert report["success"] is False
    assert "live_llm_error" in report


def test_build_closeout_backend_env_disables_scheduler_and_isolates_queue() -> None:
    env = closeout.build_closeout_backend_env(
        base_env={"APP_API_KEY": "test-key"},
        run_id="agent-claw-closeout-20260326-191421",
    )

    assert env["INGEST_SERVICE_ENABLE_WORKER"] == "true"
    assert env["INGEST_SERVICE_ENABLE_SCHEDULER"] == "false"
    assert env["REVIEW_SERVICE_ENABLE_APPLY_WORKER"] == "true"
    assert env["LLM_SERVICE_ENABLE_WORKER"] == "true"
    assert env["GMAIL_API_BASE_URL"] == "http://127.0.0.1:8765/gmail/v1/users/me"
    assert env["LLM_QUEUE_STREAM_KEY"] == "llm:parse:stream:agent-claw-closeout-20260326-191421"
    assert env["LLM_QUEUE_GROUP"] == "llm-parse-workers:agent-claw-closeout-20260326-191421"
