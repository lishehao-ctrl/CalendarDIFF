# API Consistency Test Plan

This document defines strict cross-endpoint consistency checks for CalendarDIFF.

The purpose is to ensure that multiple APIs projecting the same underlying state stay logically consistent before new agent/social/MCP layers are added on top.

## Principle

The backend may expose:

- truth reads
- aggregated posture
- preview endpoints
- execution endpoints

But if two endpoints are describing the same object or the same workflow state, they must agree on:

- identity
- phase/bucket
- counts
- active runtime posture
- write-after-read visibility

## Core Consistency Groups

## 1. Changes summary vs filtered change lists

Endpoints:

- `GET /changes/summary`
- `GET /changes`

Must stay consistent on:

- `baseline_review_pending`
  - equals pending `GET /changes?review_bucket=initial_review&intake_phase=baseline`
- `changes_pending`
  - equals pending `GET /changes?review_bucket=changes&intake_phase=replay`
- `workspace_posture.initial_review.pending_count`
  - equals `baseline_review_pending`
- `recommended_lane`
  - must agree with the highest-priority pending work implied by the underlying rows

## 2. Source list vs source observability vs sync request vs sync history

Endpoints:

- `GET /sources`
- `GET /sources/{source_id}/observability`
- `GET /sync-requests/{request_id}`
- `GET /sources/{source_id}/sync-history`
- `GET /changes/summary`

Must stay consistent on:

- `active_request_id`
- `stage`
- `substage`
- `progress`
- `operator_guidance`
- `source_product_phase`
- `source_recovery`
- aggregated source counts in `changes/summary`

If only one active source exists, `changes/summary.sources.recommended_action` should match that source's projected guidance.

## 3. Manual mutation vs manual list vs workbench summary

Endpoints:

- `POST /manual/events`
- `PATCH /manual/events/{entity_uid}`
- `DELETE /manual/events/{entity_uid}`
- `GET /manual/events`
- `GET /changes/summary`

Must stay consistent on:

- created/updated/deleted entity visibility
- lifecycle projection (`active` vs `removed`)
- `manual.active_event_count`
- default list filtering vs `include_removed=true`

## 4. Families write path vs family/raw-type reads

Endpoints:

- `POST /families`
- `PATCH /families/{family_id}`
- `GET /families`
- `GET /families/raw-types`
- `POST /families/raw-types/relink`
- `GET /families/courses`

Must stay consistent on:

- family membership of a raw type
- family `raw_types` list after relink
- raw-type row `family_id` after relink
- course scoping after writes

## 5. Preview/commit separation

Endpoints:

- `POST /changes/edits/preview`
- `POST /changes/edits`
- `POST /changes/{change_id}/label-learning/preview`
- `POST /changes/{change_id}/label-learning`

Must stay consistent on:

- preview target identity
- preview candidate effect vs committed effect
- no write-side mutation before commit

This group should be extended further once:

- `families/raw-types/relink-preview`
- `changes/{change_id}/decision-preview`
- `manual/events/preview`

exist.

## Strictness Rules

- Prefer checking multiple endpoints in one test when they describe the same state.
- Prefer asserting both counts and IDs, not counts alone.
- Prefer asserting shared projection fields exactly when possible:
  - `request_id`
  - `stage`
  - `substage`
  - `reason_code`
  - `message_code`
- After a write, always verify at least one read endpoint plus one aggregate endpoint.
- If a field is intentionally lane-specific, document that instead of asserting accidental equality.

## Phase Alignment With Agent Rollout

These tests are the precondition for:

- `docs/agent_api_layering_spec.md`
- `docs/agent_rollout_todo.md`

Reason:

- future `Context API` will aggregate current endpoint projections
- future `Proposal API` will depend on preview/commit correctness
- future `Approval API` and social confirmation will depend on write-after-read consistency
