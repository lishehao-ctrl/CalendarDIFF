---
name: calendardiff-openclaw-mcp
description: Use the CalendarDIFF MCP tools to inspect workspace state, create proposals, and manage low-risk approval tickets safely.
metadata: {"openclaw":{"emoji":"📅","requires":{"bins":["python"],"env":["CALENDARDIFF_MCP_DEFAULT_NOTIFY_EMAIL"]}}}
---

# CalendarDIFF OpenClaw MCP Skill

This skill assumes the CalendarDIFF MCP server is already configured as a fixed MCP server in OpenClaw.

Use this skill when the task is about:

- understanding the current CalendarDIFF workspace state
- understanding recent agent proposals and approval tickets
- understanding a specific change or source
- understanding a specific family
- creating a change-decision proposal
- creating a source-recovery proposal
- creating a family relink preview proposal
- creating an executable family relink commit proposal
- creating an executable label-learning add-alias proposal
- creating or confirming a low-risk approval ticket

Do not use this skill to bypass the CalendarDIFF approval workflow.

## Required workflow

Always follow this order:

1. read context first
2. check recent agent activity when resuming work
2. create a proposal if action is needed
3. create an approval ticket if the proposal is executable
4. confirm the ticket only when the user clearly wants execution

Do not skip directly from context to execution.

## Primary tools

- `get_workspace_context`
- `get_recent_agent_activity`
- `list_pending_changes`
- `list_sources`
- `get_change_context`
- `get_source_context`
- `get_family_context`
- `list_proposals`
- `create_change_decision_proposal`
- `create_change_edit_commit_proposal`
- `create_source_recovery_proposal`
- `create_family_relink_preview_proposal`
- `create_family_relink_commit_proposal`
- `create_label_learning_commit_proposal`
- `get_proposal`
- `list_approval_tickets`
- `create_approval_ticket`
- `get_approval_ticket`
- `confirm_approval_ticket`
- `cancel_approval_ticket`

## Safe operating rules

- Read-only context tools are preferred first.
- Proposal tools are preferred before any execution.
- Only confirm approval tickets for currently supported low-risk actions.
- If a proposal is not executable, stop at proposal and tell the user it stays web-only.
- If a ticket reports drift, expiry, or cancellation, do not retry blindly. Re-read context first.

## Recommended patterns

### To summarize the workspace

1. call `get_recent_agent_activity`
2. call `get_workspace_context`
3. optionally call `list_pending_changes`
3. explain:
   - what is pending
   - what the agent recently did
   - what lane should be used next
   - whether anything is blocking

When a result looks surprising, tell the user they can verify the exact MCP invocation in CalendarDIFF Settings via the MCP invocation audit surface.

### To handle one change

1. call `get_change_context`
2. if the user wants a recommendation, call `create_change_decision_proposal`
3. if the user wants a bounded pending-proposal edit on `due_date`, `due_time`, `time_precision`, or `event_name`, call `create_change_edit_commit_proposal`
4. if the proposal is executable and the user wants execution:
   - call `create_approval_ticket`
   - call `confirm_approval_ticket`

### To handle one source issue

1. call `get_source_context`
2. if the user wants a recovery recommendation, call `create_source_recovery_proposal`
3. only proceed to approval if the proposal payload is executable

### To inspect family governance safely

1. call `get_family_context`
2. if the user wants a structured recommendation, call `create_family_relink_preview_proposal`
3. if the user has already reviewed the impact and wants an executable low-risk relink, call `create_family_relink_commit_proposal`
4. if the user wants to map one observed label into an existing family for a pending change, call `create_label_learning_commit_proposal`
3. stop at preview and explain that family governance remains web-only

## Current execution limits

Currently executable:

- direct change decision proposals whose suggested action becomes `approve` or `reject`
- proposal edit commit proposals whose payload becomes `proposal_edit_commit`
- source-recovery proposals whose payload becomes `run_source_sync`
- low-risk family relink commit proposals whose payload becomes `family_relink_commit`
- low-risk label-learning add-alias proposals whose payload becomes `label_learning_add_alias_commit`

Not currently executable:

- reconnect Gmail
- update source settings
- canonical edit or broader free-form edit-then-approve
- broad family relink / rename execution beyond the low-risk single-label commit path
- manual event create / update / delete

When one of the non-executable paths is suggested, explain that the user must continue in the web app.
