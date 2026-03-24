# API Layering Contract

## Purpose

This document defines the shortest stable contract for deciding which CalendarDIFF API a caller should treat as authoritative for each lane.

It is not an endpoint inventory.
It is a lane-to-endpoint ownership map for:

- frontend page design
- embedded agent/copilot entry points
- MCP tools
- future social/channel integrations

If two endpoints can both answer a question, this document says which one is the canonical product contract and which one is only a drill-down or internal support surface.

## Core rules

1. Product truth stays in the product lane APIs.
2. Aggregated posture stays in backend-built summary/context APIs.
3. Agent execution never bypasses product truth writes.
4. MCP must reuse the agent layer, not call arbitrary truth writes directly.
5. UI should not reconstruct a lane by stitching together lower-level endpoints when a backend-built lane contract already exists.

## Layer model

### 1. Support/auth layer

Used for session, onboarding, and source connection setup.

- `/auth/*`
- `/onboarding/*`

This layer is not a daily review lane.
It exists to create or recover access to the real product lanes.

### 2. Product truth layer

These APIs are the canonical web-facing source of state and writes for the main lanes:

- `/sources/*`
- `/changes*`
- `/families*`
- `/manual/events*`
- `/settings/*`

### 3. Aggregated posture layer

These APIs are backend-built rollups and should be treated as canonical posture contracts, not as incidental convenience payloads:

- `GET /changes/summary`
- `GET /agent/context/workspace`
- `GET /sources/{source_id}/observability`

### 4. Agent layer

These APIs are the only supported boundary for agent/copilot reasoning and bounded execution:

- `/agent/context/*`
- `/agent/proposals/*`
- `/agent/approval-tickets/*`

### 5. Transport layer

This is the external transport wrapper around the agent layer:

- `/mcp`

It must not become a second business API.

## Lane contracts

## Overview

### Canonical web read

- `GET /changes/summary`

Use this as the main Overview posture contract.
It already owns:

- workspace posture
- backend-chosen recommended lane
- source rollup
- family attention
- manual lane summary

### Allowed supporting reads

- `GET /agent/context/workspace`

Use this only for the embedded agent brief / recommended tool framing.
It is not the canonical source for the rest of the Overview screen layout.

### Do not

- do not rebuild Overview by combining `/sources`, `/changes`, `/families/status`, and `/manual/events` in the UI
- do not let `/agent/context/workspace` replace `/changes/summary` as the base page contract

## Sources

### Canonical list read

- `GET /sources`

This is the canonical source for the Sources lane list.
It already carries product-facing projections such as:

- `operator_guidance`
- `source_product_phase`
- `source_recovery`
- `active_request_id`
- `sync_progress`

### Canonical detail reads

- `GET /sources/{source_id}/observability`
- `GET /sources/{source_id}/sync-history`

Use these for the source detail page, recovery posture, bootstrap summary, and timeline/history.

### Drill-down only

- `GET /sync-requests/{request_id}`

Use only when the UI needs deep sync inspection for a single request.
It is not the base contract for the Sources list or source detail shell.

### Canonical writes

- `POST /sources`
- `PATCH /sources/{source_id}`
- `DELETE /sources/{source_id}`
- `POST /sources/{source_id}/oauth-sessions`
- `POST /sources/{source_id}/sync-requests`

### Embedded agent reads/writes

- `GET /agent/context/sources/{source_id}`
- `POST /agent/proposals/source-recovery`
- `POST /agent/approval-tickets`
- `POST /agent/approval-tickets/{ticket_id}/confirm`

Use these only for recovery assistant/copilot flows.
Do not replace normal web source CRUD or setup flows with agent endpoints.

### Do not

- do not infer source trust from `/sync-requests/{id}` alone
- do not reconstruct source recovery posture in the client
- do not use agent proposal endpoints as the normal connect/reconnect/update source flow

## Changes

### Canonical list reads

- `GET /changes/summary`
- `GET /changes`

Use `/changes/summary` for queue posture and counts.
Use `/changes` for queue items.

### Canonical detail reads

- `GET /changes/{change_id}`
- `GET /changes/{change_id}/edit-context`
- `GET /changes/{change_id}/evidence/{side}/preview`

### Canonical writes

- `PATCH /changes/{change_id}/views`
- `POST /changes/{change_id}/decisions`
- `POST /changes/batch/decisions`
- `POST /changes/edits/preview`
- `POST /changes/edits`
- `POST /changes/{change_id}/label-learning/preview`
- `POST /changes/{change_id}/label-learning`

### Embedded agent reads/writes

- `GET /agent/context/changes/{change_id}`
- `POST /agent/proposals/change-decision`
- `GET /agent/proposals/{proposal_id}`
- `POST /agent/approval-tickets`
- `GET /agent/approval-tickets/{ticket_id}`
- `POST /agent/approval-tickets/{ticket_id}/confirm`
- `POST /agent/approval-tickets/{ticket_id}/cancel`

Use these when the UI is intentionally showing:

- recommendation framing
- proposal persistence
- approval-ticket gating

The direct web write remains the canonical base flow for ordinary review actions.
Approval tickets are the bounded execution path for agent/social-confirmable actions.

### Do not

- do not recompute change decision support in the client
- do not infer evidence availability from raw payload shape alone when the endpoint already returns it
- do not treat agent proposal creation as a replacement for the ordinary review UI

## Families

### Canonical reads

- `GET /families`
- `GET /families/raw-types`
- `GET /families/raw-type-suggestions`
- `GET /families/status`
- `GET /families/courses`

### Canonical writes

- `POST /families`
- `PATCH /families/{family_id}`
- `POST /families/raw-types/relink`
- `POST /families/raw-type-suggestions/{suggestion_id}/decisions`

### Current agent stance

Families now has:

- read-only context: `GET /agent/context/families/{family_id}`
- preview-only proposal: `POST /agent/proposals/family-relink-preview`

There is still no executable Families agent surface.
Families remains web-first for actual mutation.

### Do not

- do not use `/changes/{change_id}/label-learning` as the primary Families lane index
- do not route Families writes through `/agent/*`
- do not treat family preview proposals as executable actions

## Manual

### Canonical reads

- `GET /manual/events`

### Canonical writes

- `POST /manual/events`
- `PATCH /manual/events/{entity_uid}`
- `DELETE /manual/events/{entity_uid}`

### Current agent stance

Manual remains web-first.
There is no executable Manual agent surface yet.

### Do not

- do not route manual CRUD through `/agent/*`
- do not model Manual as a source-recovery subfeature

## Settings

### Canonical reads

- `GET /settings/profile`
- `GET /settings/mcp-tokens`
- `GET /settings/mcp-invocations`
- `GET /settings/channel-accounts`
- `GET /settings/channel-deliveries`

### Canonical writes

- `PATCH /settings/profile`
- `POST /settings/mcp-tokens`
- `DELETE /settings/mcp-tokens/{token_id}`
- `POST /settings/channel-accounts`
- `DELETE /settings/channel-accounts/{account_id}`

### Current agent/MCP relation

Settings owns MCP token lifecycle.
Token issuance and revocation must stay here.
`/mcp` consumes these tokens; it does not replace this management surface.

Settings also owns the user-facing audit surface for external agent access:

- recent MCP tool invocations
- MCP token lifecycle
- social channel account and delivery audit

Settings also owns the user-managed social channel foundation:

- channel account registration / revocation
- recent outbound channel delivery audit

Future Telegram / Slack / WeChat bindings should plug into this boundary instead of inventing a second integration surface.

### Do not

- do not create tokens anywhere except `/settings/mcp-tokens`
- do not expose token secrets again after the creation response

## Onboarding and source setup

### Canonical reads

- `GET /onboarding/status`

### Canonical writes

- `POST /onboarding/registrations`
- `POST /onboarding/canvas-ics`
- `POST /onboarding/gmail/oauth-sessions`
- `POST /onboarding/gmail-skip`
- `POST /onboarding/monitoring-window`

Use onboarding only until the user reaches the normal lanes.
Do not continue to treat onboarding APIs as day-to-day product lane contracts after setup is complete.

## Agent and MCP contract

## `/agent/context/*`

Purpose:

- structured read-only context for embedded agent/copilot reasoning

Rules:

- derived from product truth
- safe to use for recommendation framing
- not a substitute for lane base reads

## `/agent/proposals/*`

Purpose:

- persist a proposed action and its snapshot

Rules:

- proposal creation is not execution
- proposal rows are auditable state
- proposal endpoints should be used only where proposal persistence is part of the UX
- list reads such as `GET /agent/proposals` are the canonical way to show recent proposal history in the product

## `/agent/approval-tickets/*`

Purpose:

- the only bounded execution gateway for agent/social-confirmable actions

Rules:

- execution must remain narrow
- drift protection and idempotency belong here
- product truth writes still happen in business services beneath this layer
- list reads such as `GET /agent/approval-tickets` and `GET /agent/activity/recent` are the canonical way to show recent ticket/action history

## `/mcp`

Purpose:

- external transport for the same bounded agent capabilities

Rules:

- must stay token-scoped per user
- must not expose broader write power than `/agent/*`
- should reuse agent/service logic, not fork semantics

## Current “do this, not that” summary

- Overview posture: use `GET /changes/summary`, not client-side lane reconstruction.
- Overview agent brief: use `GET /agent/context/workspace`, not raw lane calls.
- Sources list: use `GET /sources`, not `/sync-requests/*`.
- Source detail: use `/sources/{id}/observability` and `/sources/{id}/sync-history`; use `/sync-requests/{id}` only for deep drill-down.
- Changes queue: use `GET /changes`; do not rebuild queue semantics locally.
- Change decisions: use `/changes/*` as the base web write path; use `/agent/*` only when proposal/ticket UX is intentional.
- Families and Manual: stay web-first until explicit preview/execution boundaries are added.
- MCP access: manage tokens only under `/settings/mcp-tokens`; execute bounded actions only through `/mcp` -> `/agent/*`.
