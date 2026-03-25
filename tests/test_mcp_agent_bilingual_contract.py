from __future__ import annotations

import inspect

from services.mcp_server import main as mcp_main


def test_mcp_instructions_are_bilingual() -> None:
    assert "CalendarDIFF MCP server" in mcp_main.INSTRUCTIONS
    assert "CalendarDIFF MCP 服务" in mcp_main.INSTRUCTIONS


def test_user_facing_mcp_tools_accept_language_code() -> None:
    for fn in (
        mcp_main.get_workspace_context_tool,
        mcp_main.get_recent_agent_activity_tool,
        mcp_main.get_change_context_tool,
        mcp_main.get_source_context_tool,
        mcp_main.get_family_context_tool,
        mcp_main.create_change_decision_proposal_tool,
        mcp_main.create_source_recovery_proposal_tool,
        mcp_main.create_change_edit_commit_proposal_tool,
        mcp_main.create_family_relink_preview_proposal_tool,
        mcp_main.create_family_relink_commit_proposal_tool,
        mcp_main.create_label_learning_commit_proposal_tool,
        mcp_main.get_proposal_tool,
        mcp_main.list_proposals_tool,
        mcp_main.create_approval_ticket_tool,
        mcp_main.get_approval_ticket_tool,
        mcp_main.list_approval_tickets_tool,
        mcp_main.confirm_approval_ticket_tool,
        mcp_main.cancel_approval_ticket_tool,
    ):
        assert "language_code" in inspect.signature(fn).parameters
