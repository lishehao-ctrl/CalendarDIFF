# Claw Smoke Runbook

This runbook is the shortest manual path for validating that CalendarDIFF is formally usable through the current Claw-first MCP workflow.

It does not require a real Claw desktop run.
It validates the exact backend-side workflow that Claw is expected to follow.

## Preconditions

- local CalendarDIFF backend code is available
- PostgreSQL is available for the local workspace
- MCP server can be started with `scripts/run_calendardiff_mcp.sh`
- a seeded fixture user can be created through `scripts/seed_agent_live_eval_fixture.py`

## Manual validation path

1. Start the MCP server

```bash
CALENDARDIFF_MCP_DEFAULT_NOTIFY_EMAIL=agent-live-eval@example.com \
scripts/run_calendardiff_mcp.sh
```

2. Confirm OpenClaw/QClaw skill visibility

```bash
openclaw skills list --eligible
openclaw skills info calendardiff-openclaw-mcp
```

3. Seed a known local fixture

```bash
python scripts/seed_agent_live_eval_fixture.py
```

4. Inspect recent agent activity

- use `get_recent_agent_activity`
- confirm it returns recent proposal/ticket rows or an empty but valid result

5. Inspect workspace posture

- use `get_workspace_context`
- confirm the workspace returns valid posture and pending work

6. Inspect one pending change

- use `list_pending_changes`
- then `get_change_context`

7. Create one change proposal

- use `create_change_decision_proposal`
- confirm it returns:
  - `proposal_id`
  - `origin_kind = mcp`
  - `origin_request_id` when request context is present

8. Create one approval ticket

- use `create_approval_ticket`
- confirm it returns:
  - `ticket_id`
  - `origin_kind = mcp`
  - lifecycle / transition contract fields

9. Confirm one low-risk ticket

- use `confirm_approval_ticket`
- confirm the resulting ticket is terminal and executable

10. Run one family relink preview

- use `get_family_context`
- use `create_family_relink_preview_proposal`
- confirm it succeeds
- confirm it remains web-only:
  - `execution_mode = web_only`
  - `can_create_ticket = false`

11. Verify recent activity again

- use `get_recent_agent_activity`
- confirm the newly created proposal/ticket now appear

12. Verify Settings-side MCP audit

- call `GET /settings/mcp-invocations`
- confirm recent rows include the tool names used above
- confirm proposal/ticket IDs are linked where expected

## Expected web-only stops

These should not be forced through approval-ticket execution:

- reconnect Gmail
- source settings updates
- family governance execution
- manual writes

If Claw reaches one of these, it should stop at preview/proposal and direct the user back to the web app.

## Reproducible local smoke helper

For a non-interactive backend-side version of this flow, run:

```bash
python scripts/run_claw_mcp_smoke.py
```

The script should:

- seed a known fixture
- execute the MCP-side workflow
- fetch Settings-side MCP audit
- write results under `output/`
