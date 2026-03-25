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
            "executable_actions_exercised": {
                "change_decision": True,
                "proposal_edit_commit": True,
                "run_source_sync": True,
                "family_relink_commit": True,
                "label_learning_add_alias_commit": True,
            },
        },
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
    )

    assert report["success"] is True
    assert report["passed"] is True
    assert report["tool_families_exercised"]["read_context"] is True
    assert report["tool_families_exercised"]["proposal"] is True
    assert report["tool_families_exercised"]["approval"] is True
    assert report["smoke_actions_exercised"]["proposal_edit_commit"] is True
    assert report["smoke_actions_exercised"]["family_low_risk_execute"] is True
    assert report["executable_actions_exercised"]["label_learning_add_alias_commit"] is True
    assert report["family_relink_preview_non_executable"] is True
