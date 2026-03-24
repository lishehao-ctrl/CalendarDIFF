# Agent Rollout TODO

This document is the phased implementation checklist for introducing an agent layer into CalendarDIFF without weakening the existing deterministic workflow core.

## Non-Negotiable Rules

- The agent layer does not own canonical truth.
- The agent layer does not bypass `Sources / Changes / Families / Manual` business services.
- Social channels do not write directly to truth APIs.
- All executable agent actions must become approval tickets first.
- High-risk actions remain web-only until explicitly reclassified.

## Target Architecture

Split backend responsibilities into four API layers:

1. `Truth API`
   - existing product APIs
   - source of fact for product state and writes
2. `Context API`
   - aggregated agent-readable context
   - no writes
3. `Proposal API`
   - structured suggestions only
   - no direct execution
4. `Approval API`
   - ticket creation / confirmation / cancellation
   - only safe execution gateway for agent-driven actions

## Phase 0. Interface Layering Baseline

Goal:
- clarify which current endpoints are truth APIs and which new agent APIs need to exist

Reference:
- `docs/agent_api_layering_spec.md`

Tasks:
- [ ] audit existing public APIs and classify each as:
  - truth read
  - truth write
  - aggregated posture
  - preview-only
- [ ] define stable backend-owned code fields for high-frequency guidance/error/recommendation text
- [ ] identify missing `revision` / `version` / idempotency boundaries on write paths
- [ ] define a canonical `risk_level` model for user actions:
  - `low`
  - `medium`
  - `high`
- [ ] define which existing actions can ever be social-confirmable
- [ ] document which actions stay web-only

Exit criteria:
- [ ] one clear mapping from current endpoints to `Truth API`
- [ ] one approved list of new `Context / Proposal / Approval` endpoints
- [ ] one approved action-risk matrix

## Phase 1. Agent Read-Only Context Layer

Goal:
- let an agent understand the system before it can suggest or execute anything

Backend tasks:
- [ ] add `app/modules/agents/` module boundary
- [ ] add `agent_context_builder`
- [ ] add read-only context schemas for:
  - `workspace`
  - `change detail`
  - `source detail`
  - `family detail`
- [ ] add endpoints:
  - [ ] `GET /agent/context/workspace`
  - [ ] `GET /agent/context/changes/{change_id}`
  - [ ] `GET /agent/context/sources/{source_id}`
  - [x] `GET /agent/context/families/{family_id}`
- [ ] normalize these context payloads:
  - current posture
  - why action is needed
  - recommended next action
  - known risk signals

UI tasks:
- [ ] add a read-only copilot panel in web
- [ ] show:
  - what is happening now
  - why it matters
  - what the user should do next

Exit criteria:
- [ ] agent can explain `Changes`, `Sources`, and `Families` using only structured context
- [ ] no agent write path exists yet

## Phase 2. Structured Proposal Layer

Goal:
- let the agent produce structured suggestions without executing them

Backend tasks:
- [ ] add `agent_proposals` storage
- [ ] define proposal schema:
  - `proposal_type`
  - `target_kind`
  - `target_id`
  - `reason`
  - `risk_level`
  - `confidence`
  - `payload`
  - `expires_at`
- [ ] add proposal endpoints:
  - [ ] `POST /agent/proposals/change-decision`
  - [ ] `POST /agent/proposals/source-recovery`
  - [x] `POST /agent/proposals/family-relink-preview`
- [ ] standardize proposal outputs for:
  - approve
  - reject
  - edit-then-approve draft
  - reconnect / rerun-sync recommendation
  - family relink preview

UI tasks:
- [ ] show “agent suggestion” blocks on:
  - `Changes`
  - `Sources`
  - `Families`
- [ ] clearly distinguish:
  - suggestion
  - preview
  - actual commit

Exit criteria:
- [ ] agent can emit structured proposals
- [ ] proposals are inspectable and auditable
- [ ] proposals still cannot mutate truth directly

## Phase 3. Approval Ticket Execution Layer

Goal:
- create a safe bridge between proposal and execution

Backend tasks:
- [ ] add `approval_tickets`
- [ ] ticket fields must include:
  - `ticket_id`
  - `user_id`
  - `action_type`
  - `target_kind`
  - `target_id`
  - `payload_json`
  - `payload_hash`
  - `entity_revision`
  - `risk_level`
  - `status`
  - `expires_at`
- [ ] add endpoints:
  - [ ] `POST /agent/approval-tickets`
  - [ ] `GET /agent/approval-tickets/{ticket_id}`
  - [ ] `POST /agent/approval-tickets/{ticket_id}/confirm`
  - [ ] `POST /agent/approval-tickets/{ticket_id}/cancel`
- [ ] enforce confirm-time validation:
  - [ ] ticket not expired
  - [ ] user still authorized
  - [ ] target revision unchanged
  - [ ] payload hash unchanged
  - [ ] action still allowed for risk level
- [ ] route confirmed tickets back through existing business services, not direct DB writes

Policy tasks:
- [ ] mark low-risk actions eligible for social confirmation
- [ ] mark medium/high-risk actions as web-only or double-confirm

Exit criteria:
- [ ] no agent-driven execution bypasses approval tickets
- [ ] confirmation is idempotent and drift-safe

## Phase 4. First Social Approval Channel

Goal:
- let the user read status and confirm low-risk actions outside the web app

Recommended first channel:
- `Telegram` or `Slack`

Not first:
- `WeChat`
- broad multi-channel rollout

Backend tasks:
- [x] add `channel_accounts`
- [x] add `channel_deliveries`
- [ ] add signed callback verification
- [ ] add deep-link generation back to web
- [ ] define social-safe actions:
  - [ ] view status
  - [ ] view next actions
  - [ ] approve low-risk ticket
  - [ ] reject low-risk ticket
  - [ ] trigger sync-now

Product tasks:
- [ ] define short summary card format:
  - what happened
  - why it matters
  - what action is available
  - when user must open web instead

Exit criteria:
- [ ] one social channel can safely confirm low-risk tickets
- [ ] high-risk actions still redirect to web

## Phase 5. MCP / External Agent Surface

Goal:
- make CalendarDIFF operable by external agents like Claude/Codex/ChatGPT via standard tooling

Backend tasks:
- [ ] define MCP resources:
  - workspace posture
  - source observability
  - pending changes
  - family posture
- [ ] define MCP tools:
  - get change context
  - preview decision
  - confirm ticket
  - get source posture
  - run sync
  - preview family relink
- [ ] expose only approved tool boundaries
- [ ] ensure MCP tools map to:
  - truth reads
  - proposal creation
  - approval confirmation
  and not direct internal state mutation

Exit criteria:
- [ ] external agent can read and operate through approved tool boundaries
- [ ] no MCP path bypasses approval rules

## Phase 6. Optional WeChat / Additional Channels

Goal:
- expand social confirmation once the approval-ticket model is stable

Tasks:
- [ ] evaluate WeChat / WeCom interaction limits
- [ ] adapt social card payloads to channel capability
- [ ] reuse existing approval ticket backend instead of channel-specific logic forks

Exit criteria:
- [ ] second channel adds reach, not duplicate backend complexity

## Action Risk Matrix Draft

Low risk candidates:
- [ ] reject obvious noise
- [ ] approve clear low-risk baseline item
- [ ] run sync now
- [ ] acknowledge reconnect needed

Medium risk candidates:
- [ ] approve replay change with moderate ambiguity
- [ ] source recovery actions that change runtime posture

High risk web-only:
- [ ] edit then approve
- [ ] family relink
- [ ] family rename with broad impact
- [ ] manual create
- [ ] manual update
- [ ] manual delete
- [ ] destructive removed-item approval

## Cross-Cutting Requirements

- [ ] every agent-readable payload should prefer structured codes over freeform text
- [ ] every executable action should have a preview form before commit
- [ ] every confirmed action should produce an audit record
- [ ] every social callback should be signed and replay-safe
- [ ] every channel action should degrade to a web deep-link when the action is too risky or too stale

## Recommended Execution Order

1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5
7. Phase 6

Do not start social-channel execution before approval tickets exist.
Do not start MCP execution tools before context and approval boundaries are stable.
