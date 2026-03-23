# Agent API Layering Spec

This document defines the Phase 0 API boundary for introducing an agent layer into CalendarDIFF.

It is intentionally backend-first and execution-oriented.

## Goal

Before adding any agent, social channel, or MCP surface, the backend API must be split into explicit layers:

1. `Truth API`
2. `Context API`
3. `Proposal API`
4. `Approval API`

The goal is not to duplicate all existing product endpoints.
The goal is to stop agents and social channels from directly improvising on top of user-facing lane APIs.

## Design Rules

- Existing product truth remains in current backend modules.
- New agent APIs must call existing business services, not bypass them.
- Social channels never execute truth writes directly.
- Agent execution must always go through approval tickets.
- Preview and commit must stay separate.
- If an action has no safe preview or no stable target revision, it is not social-confirmable yet.

## Current Backend Surface Classification

## A. Truth Read APIs

These are current fact/product-state reads and remain the canonical source for app state.

### Auth / profile

- `GET /auth/session`
- `GET /settings/profile`

### Sources

- `GET /sources`
- `GET /sources/{source_id}/observability`
- `GET /sources/{source_id}/sync-history`
- `GET /sync-requests/{request_id}`

### Changes

- `GET /changes`
- `GET /changes/{change_id}`
- `GET /changes/{change_id}/edit-context`
- `GET /changes/{change_id}/evidence/{side}/preview`

### Families

- `GET /families`
- `GET /families/status`
- `GET /families/courses`
- `GET /families/raw-types`
- `GET /families/raw-type-suggestions`

### Manual

- `GET /manual/events`

### Onboarding

- `GET /onboarding/status`

## B. Truth Write APIs

These mutate product truth or product-visible workflow state.
They remain web-first and business-service-owned.

### Auth / onboarding / sources

- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`
- `POST /onboarding/registrations`
- `POST /onboarding/canvas-ics`
- `POST /onboarding/gmail/oauth-sessions`
- `POST /onboarding/gmail-skip`
- `POST /onboarding/monitoring-window`
- `POST /sources`
- `PATCH /sources/{source_id}`
- `DELETE /sources/{source_id}`
- `POST /sources/{source_id}/oauth-sessions`
- `POST /sources/{source_id}/sync-requests`
- `POST /sources/{source_id}/webhooks/{provider}`
- `PATCH /settings/profile`

### Changes

- `PATCH /changes/{change_id}/views`
- `POST /changes/{change_id}/decisions`
- `POST /changes/batch/decisions`
- `POST /changes/edits`
- `POST /changes/{change_id}/label-learning`

### Families

- `POST /families`
- `PATCH /families/{family_id}`
- `POST /families/raw-types/relink`
- `POST /families/raw-type-suggestions/{suggestion_id}/decisions`

### Manual

- `POST /manual/events`
- `PATCH /manual/events/{entity_uid}`
- `DELETE /manual/events/{entity_uid}`

## C. Existing Aggregated / Posture APIs

These are not raw truth rows.
They are already backend-built summaries and should be treated as the first building blocks for agent context.

- `GET /changes/summary`
  - workbench posture
  - lane recommendation
  - source/family/manual rollup
- `GET /sources`
  - operator guidance
  - source product phase
  - source recovery
- `GET /sources/{source_id}/observability`
  - bootstrap summary
  - runtime posture
  - operator guidance
- `GET /onboarding/status`
  - onboarding stage
  - source health messaging
- `GET /families/status`
  - mapping rebuild posture

These should not be replaced by agent endpoints.
They should be reused by `Context API`.

## D. Existing Preview-Only APIs

These are safe, structured preview boundaries and should be reused by the future `Proposal API`.

- `GET /changes/{change_id}/evidence/{side}/preview`
- `POST /changes/edits/preview`
- `POST /changes/{change_id}/label-learning/preview`

Current gap:

- there is no `families/raw-types/relink-preview`
- there is no `manual/events/preview`
- there is no `changes/{change_id}/decision-preview`

## Current Gaps Blocking Agent/Social Execution

## 1. No explicit agent-readable context endpoints

Today an agent would have to stitch together:

- `/changes/summary`
- `/changes/{id}`
- `/sources`
- `/sources/{id}/observability`
- `/families/status`
- `/families/raw-types`
- `/manual/events`

This is acceptable for the web app.
It is not acceptable as the long-term contract for agents and social channels.

## 2. No approval-ticket execution boundary

Today write APIs execute immediately.

That is fine for the web app, but not for:

- Telegram/Slack/WeChat confirmation
- MCP-driven execution
- agent proposals that may become stale before confirm

## 3. No stable revision token on most write surfaces

Current write request shapes do not carry a target revision guard:

- `ChangeDecisionRequest`
- `ChangeEditRequest`
- `CourseRawTypeMoveRequest`
- `CourseWorkItemFamilyUpdateRequest`
- `ManualEventWriteRequest`

The current APIs rely on current DB state, but they do not expose a first-class optimistic concurrency token suitable for external confirmation channels.

Implication:

- approval-ticket execution cannot safely depend on raw endpoint payloads alone
- Phase 3 must introduce target revision capture inside tickets, or the truth APIs must expose explicit revision fields

## 4. Idempotency is inconsistent

Current state:

- `POST /sources/{source_id}/sync-requests` supports `Idempotency-Key`
- change decisions expose `idempotent` in response
- manual mutations expose `idempotent` in response
- family writes do not expose a unified idempotency contract

Implication:

- agent execution should not call truth writes directly
- approval ticket confirmation should become the idempotent execution boundary

## 5. Preview coverage is incomplete

Safe preview exists for:

- change edit
- label learning
- evidence read

Safe preview does not yet exist for:

- change approve/reject outcomes as a first-class endpoint
- raw-type relink
- family rename/update impact
- manual create/update/delete impact

Implication:

- those actions are not good social-channel candidates yet

## Layer Definition

## Layer 1. Truth API

Owner:
- existing product modules

Allowed consumers:
- web frontend
- internal agent services
- MCP tools only indirectly

Rules:
- remains canonical source of product state
- remains the only place that performs business truth writes
- should continue code-ifying high-frequency human-facing fields

## Layer 2. Context API

Owner:
- new `app/modules/agents/context_*`

Purpose:
- aggregate the minimum structured context needed for agent reasoning

Rules:
- read-only
- built from Truth API services, not from duplicated SQL drift
- must not introduce a parallel product truth model

### Proposed endpoints

- `GET /agent/context/workspace`
- `GET /agent/context/changes/{change_id}`
- `GET /agent/context/sources/{source_id}`
- `GET /agent/context/families/{family_id}`

### Required payload properties

Each context payload should include:

- `posture`
- `recommended_next_action`
- `recommended_next_action_code`
- `risk_level`
- `risk_factors`
- `blocking_conditions`
- `available_next_tools`

### Context endpoint responsibilities

`/agent/context/workspace`
- summarize:
  - current lane posture
  - top pending changes
  - source issues
  - family backlog
  - whether user should stay in web or can safely confirm elsewhere

`/agent/context/changes/{change_id}`
- include:
  - change item
  - decision support
  - current evidence availability
  - whether approve/reject/edit are eligible
  - whether action is low/medium/high risk

`/agent/context/sources/{source_id}`
- include:
  - source posture
  - observability
  - operator guidance
  - recovery suggestion set
  - safe actions such as `run_sync` or `reconnect`

`/agent/context/families/{family_id}`
- include:
  - canonical family
  - related observed labels/raw types
  - pending suggestion posture
  - whether family actions require web-only handling

## Layer 3. Proposal API

Owner:
- new `app/modules/agents/proposal_*`

Purpose:
- turn agent reasoning into structured, inspectable suggestions

Rules:
- no direct truth mutation
- proposal output must be structured, not raw prose only
- proposal input should reference context endpoints

### Proposed endpoints

- `POST /agent/proposals/change-decision`
- `POST /agent/proposals/source-recovery`
- `POST /agent/proposals/family-action`
- `POST /agent/proposals/manual-action`

### Proposal response shape

- `proposal_id`
- `proposal_type`
- `target_kind`
- `target_id`
- `summary`
- `reason`
- `reason_code`
- `risk_level`
- `confidence`
- `suggested_action`
- `suggested_payload`
- `preview_available`
- `preview_requirements`
- `expires_at`

### V1 proposal scope

Allowed in v1:

- change approve suggestion
- change reject suggestion
- source reconnect / rerun sync recommendation
- family relink suggestion preview

Not recommended in v1:

- manual full mutation proposal
- batch family governance actions
- broad batch change execution

## Layer 4. Approval API

Owner:
- new `app/modules/agents/approval_*`

Purpose:
- become the only execution entrypoint for agent/social actions

Rules:
- approval confirm is the idempotent execution boundary
- confirm-time validation must re-check drift and permission
- confirmed tickets call existing business services

### Proposed endpoints

- `POST /agent/approval-tickets`
- `GET /agent/approval-tickets/{ticket_id}`
- `POST /agent/approval-tickets/{ticket_id}/confirm`
- `POST /agent/approval-tickets/{ticket_id}/cancel`

### Ticket fields

- `ticket_id`
- `proposal_id`
- `user_id`
- `channel`
- `action_type`
- `target_kind`
- `target_id`
- `payload_json`
- `payload_hash`
- `target_revision`
- `risk_level`
- `status`
- `expires_at`
- `confirmed_at`
- `executed_at`

### Confirm-time checks

- user still owns target
- ticket not expired
- ticket not already consumed
- target revision unchanged
- payload hash unchanged
- action still allowed by current risk rules

## Action Risk Matrix For V1

## Low risk

Eligible for future social confirmation after approval tickets exist:

- reject obvious noise
- approve very clear low-risk change
- run sync now
- acknowledge reconnect needed

## Medium risk

Require web confirmation first, or later double-confirmation:

- approve replay change with moderate ambiguity
- source recovery action that changes monitoring posture

## High risk

Web-only in v1:

- change edit then approve
- family relink
- family rename/update with broad effect
- manual create
- manual update
- manual delete
- removed-item destructive approval

## Concrete Phase 0 Deliverables

## 1. Keep current lane APIs as Truth API

No rename required in this phase.

## 2. Add agent module boundary

Create:

- `app/modules/agents/__init__.py`
- `app/modules/agents/context_service.py`
- `app/modules/agents/proposal_service.py`
- `app/modules/agents/approval_service.py`
- `app/modules/agents/schemas.py`
- `app/modules/agents/router.py`

Only the module boundary and read-only context endpoints should be implemented first.

## 3. Add revision strategy decision

Before approval execution is built, choose one of:

- explicit `revision` field on change/family/manual payloads
- or approval-ticket-owned target snapshot + drift check logic

Recommended:

- keep Truth APIs stable for now
- implement ticket-owned target snapshot and drift check in the approval layer

## 4. Add missing preview backlog

Track these as explicit follow-up API gaps:

- `POST /families/raw-types/relink-preview`
- `POST /changes/{change_id}/decision-preview`
- `POST /manual/events/preview`

They do not all need to be built before Phase 1.
They do need to exist before broad social execution.

## Immediate Next Implementation Step

Phase 1 should implement only:

- `app/modules/agents/`
- `GET /agent/context/workspace`
- `GET /agent/context/changes/{change_id}`
- `GET /agent/context/sources/{source_id}`

Do not implement proposal or approval execution in the same pass.
