# OpenClaw / QClaw Integration

This document explains how to use CalendarDIFF from OpenClaw or QClaw through the CalendarDIFF MCP server.

## Goal

Use OpenClaw as an external agent client while keeping CalendarDIFF as the owner of:

- canonical truth
- proposals
- approval tickets

OpenClaw should operate through the MCP surface, not by bypassing the backend workflow.

## Important limitation

OpenClaw's ACP bridge does not support per-session `mcpServers`.

Implication:

- do not rely on dynamic per-session MCP injection
- configure CalendarDIFF as a fixed MCP server for the OpenClaw agent or gateway instead

Reference:

- [OpenClaw ACP bridge](https://docs.openclaw.ai/cli/acp)

## Public multi-user access

For real users connecting their own CalendarDIFF accounts:

1. deploy the CalendarDIFF MCP server in `public` mode with `streamable-http`
2. each user creates an MCP access token from CalendarDIFF Settings
3. the MCP client connects using:
   - the MCP URL
   - a Bearer token

Do not use `CALENDARDIFF_MCP_DEFAULT_NOTIFY_EMAIL` for public multi-user access.
That is local/dev mode only.

## What CalendarDIFF already exposes

### Read/context tools

- `get_workspace_context`
- `get_recent_agent_activity`
- `list_pending_changes`
- `list_sources`
- `get_change_context`
- `get_source_context`
- `get_family_context`

### Proposal tools

- `list_proposals`
- `create_change_decision_proposal`
- `create_source_recovery_proposal`
- `create_family_relink_preview_proposal`
- `get_proposal`

### Approval tools

- `list_approval_tickets`
- `create_approval_ticket`
- `get_approval_ticket`
- `confirm_approval_ticket`
- `cancel_approval_ticket`

### Resources

- `calendardiff://workspace`
- `calendardiff://pending-changes`
- `calendardiff://sources`

## Start the MCP server

Recommended local/dev command:

```bash
CALENDARDIFF_MCP_DEFAULT_NOTIFY_EMAIL=you@example.com \
scripts/run_calendardiff_mcp.sh
```

This starts the MCP server over `stdio` by default.

Optional alternate transport:

```bash
CALENDARDIFF_MCP_DEFAULT_NOTIFY_EMAIL=you@example.com \
CALENDARDIFF_MCP_TRANSPORT=streamable-http \
scripts/run_calendardiff_mcp.sh
```

## OpenClaw / QClaw workspace

OpenClaw loads workspace skills from:

- `<workspace>/skills`

Reference:

- [OpenClaw agent workspace](https://docs.openclaw.ai/agent-workspace)

If you want OpenClaw to load the CalendarDIFF skill in this repo, set the OpenClaw workspace to this repository root.

Then verify:

```bash
openclaw skills list
openclaw skills list --eligible
openclaw skills info calendardiff-openclaw-mcp
```

Reference:

- [OpenClaw skills CLI](https://docs.openclaw.ai/cli/skills)

## Skill included in this repo

Workspace skill:

- `skills/calendardiff-openclaw-mcp/SKILL.md`

This skill assumes the MCP server is already configured and teaches OpenClaw how to:

- inspect recent agent activity when resuming work
- read CalendarDIFF context first
- create proposals before action
- create approval tickets before execution
- avoid unsupported or web-only execution paths

## Recommended operating pattern

Use this exact order:

1. `get_recent_agent_activity`
2. `get_workspace_context`
3. `get_change_context` or `get_source_context` or `get_family_context`
4. `create_*_proposal`
5. `create_approval_ticket`
6. `confirm_approval_ticket`

Do not jump directly from context to execution.

## Current safe execution scope

Currently executable through OpenClaw:

- direct change decision proposals whose suggested action is `approve` or `reject`
- source recovery proposals whose payload becomes `run_source_sync`

Still web-only:

- reconnect Gmail
- update source settings
- edit-then-approve
- family governance writes
- manual writes

## Suggested first validation

Once OpenClaw is configured against the MCP server:

1. ask it to summarize the current workspace
2. ask it to summarize recent agent activity
3. ask it to explain one pending change
4. ask it to create a proposal for that change
5. ask it to create an approval ticket
6. ask it to confirm the ticket only if the action is low-risk

That validates the full path without widening execution scope.
