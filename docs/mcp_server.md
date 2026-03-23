# MCP Server

CalendarDIFF now exposes a dedicated MCP server for external agent clients such as OpenClaw.

## Entry Point

- `python -m services.mcp_server.main`

Default transport:

- `stdio`

Optional transport:

- set `CALENDARDIFF_MCP_TRANSPORT=streamable-http`

## Modes

### Local mode

Default:

- `CALENDARDIFF_MCP_MODE=local`

Identity can come from:

- `CALENDARDIFF_MCP_DEFAULT_NOTIFY_EMAIL`
- or explicit `notify_email` tool arguments

### Public mode

Use:

- `CALENDARDIFF_MCP_MODE=public`

Public mode is for multi-user remote access.

In public mode:

- the server expects Bearer token auth
- the authenticated token determines the CalendarDIFF user
- tool calls no longer rely on `notify_email`
- resources remain best suited to local/dev mode unless a default user is configured

Recommended public env:

```bash
CALENDARDIFF_MCP_MODE=public
CALENDARDIFF_MCP_TRANSPORT=streamable-http
CALENDARDIFF_MCP_HOST=0.0.0.0
CALENDARDIFF_MCP_PORT=8766
```

## User Resolution

The MCP server is user-scoped.

Preferred setup in local mode:

- set `CALENDARDIFF_MCP_DEFAULT_NOTIFY_EMAIL=<user notify email>`

If that env var is not set, tools that need a user can still receive:

- `notify_email`

## Public user access tokens

CalendarDIFF users can create per-user MCP access tokens through:

- `GET /settings/mcp-tokens`
- `POST /settings/mcp-tokens`
- `DELETE /settings/mcp-tokens/{token_id}`

Suggested public flow:

1. user logs into the CalendarDIFF web app
2. user creates an MCP token
3. user configures QClaw/OpenClaw with:
   - MCP URL
   - Bearer token
4. the public MCP server resolves that user from the token

## Current Tool Surface

Read tools:

- `get_workspace_context`
- `list_pending_changes`
- `list_sources`
- `get_change_context`
- `get_source_context`

Proposal tools:

- `create_change_decision_proposal`
- `create_source_recovery_proposal`
- `get_proposal`

Approval tools:

- `create_approval_ticket`
- `get_approval_ticket`
- `confirm_approval_ticket`
- `cancel_approval_ticket`

## Current Resource Surface

- `calendardiff://workspace`
- `calendardiff://pending-changes`
- `calendardiff://sources`

These resources use the configured default user.

For public multi-user access, prefer tools over resources because tools can resolve the authenticated user from MCP auth context.

## Execution Scope

The MCP server only exposes currently safe agent execution paths.

Currently executable through approval tickets:

- direct change decision proposals whose action is `approve` or `reject`
- source recovery proposals whose action is `run_source_sync`

Not executable yet:

- reconnect Gmail
- ICS/settings update flows
- edit-then-approve
- family governance writes
- manual event writes

## OpenClaw / QClaw Integration Shape

Recommended pattern:

1. configure CalendarDIFF MCP as a fixed MCP server in OpenClaw
2. in local mode, set `CALENDARDIFF_MCP_DEFAULT_NOTIFY_EMAIL`
3. in public mode, configure an MCP Bearer token instead
4. use an OpenClaw skill to teach:
   - read workspace first
   - create proposals before action
   - create approval tickets before execution
   - confirm only low-risk tickets

Do not let OpenClaw call product truth writes directly when the MCP tool already exists.
