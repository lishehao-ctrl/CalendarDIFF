# Agent + Claw Closeout

This document freezes the current `Agent + Claw` mainline as a usable integration contract.

The purpose of this phase is closeout and validation, not capability expansion.

## Frozen MCP tool set

The Claw-facing MCP surface is frozen to these tools:

### Read / context

- `get_recent_agent_activity`
- `get_workspace_context`
- `list_pending_changes`
- `list_sources`
- `get_change_context`
- `get_source_context`
- `get_family_context`

### Proposals

- `list_proposals`
- `get_proposal`
- `create_change_decision_proposal`
- `create_source_recovery_proposal`
- `create_family_relink_preview_proposal`

### Approval

- `list_approval_tickets`
- `get_approval_ticket`
- `create_approval_ticket`
- `confirm_approval_ticket`
- `cancel_approval_ticket`

Do not add more MCP tools in this phase.

## Frozen execution boundaries

Currently executable through approval tickets:

- direct change decision proposals whose action becomes `approve` or `reject`
- source recovery proposals whose payload becomes `run_source_sync`

Still web-only:

- reconnect Gmail
- source settings update flows
- edit-then-approve
- family governance execution
- manual writes

## Required audit surfaces

The current Claw contract relies on two distinct read surfaces:

- `recent agent activity`
- `GET /settings/mcp-invocations`

The following correlation fields are frozen:

- `origin_kind`
- `origin_label`
- `origin_request_id`

Do not change the meaning of these fields in this phase.

## Explicit deferrals

The following are intentionally out of scope:

- Telegram / Slack / WeChat transport adapters
- channel webhook / callback productization
- unrelated `frontend/*` dirty worktree changes
- unrelated `llm_gateway/*` dirty worktree changes
- unrelated `sources/*` dirty worktree changes
- OpenAPI snapshot refresh while unrelated dirty backend work exists

## OpenAPI note

`contracts/openapi/public-service.json` is intentionally deferred in this closeout.

Do not refresh or commit the snapshot as part of the Claw closeout while unrelated backend work is still dirty.

OpenAPI contract sync is a separate pass after those unrelated worktrees are committed or removed.

## Acceptance rule

The Claw contract is considered closed for this phase when:

- the strict pytest bundle passes
- `scripts/run_agent_live_eval.py --scenario-set full` passes
- `scripts/run_claw_mcp_smoke.py` passes
- `scripts/run_agent_claw_strict_eval.py` produces a passing `FINAL_REPORT`
