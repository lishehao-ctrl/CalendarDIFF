---
name: calendardiff-entity-first
description: Use when changing CalendarDIFF semantic logic, review flows, canonical event state, route/docs/contracts cleanup, or other work that must stay aligned with PURPOSE.md, ENTITY_FIRST_SEMANTIC_SPEC.md, and the monolith runtime. Skip for purely deploy-only or cosmetic UI tasks.
metadata:
  short-description: CalendarDIFF semantic guardrails
---

# CalendarDIFF Entity-First

Use this skill for CalendarDIFF work that changes product semantics or repo truth, especially:

- Gmail / ICS detection logic
- proposal generation and review flows
- `event_entities`, `changes`, `source_event_observations`, link tables
- manual event, family, raw-type, or notification behavior
- API / OpenAPI / docs cleanup that must match the current product model

Do not use this skill for deploy-only work. For GitHub/AWS/nginx/live host tasks, use [aws-release](../aws-release/SKILL.md).

## Read first

Read these before editing semantic behavior:

- `PURPOSE.md`
- `ENTITY_FIRST_SEMANTIC_SPEC.md`

Read these when relevant:

- API surface or route changes: `docs/api_surface_current.md`
- Runtime/module boundary changes: `docs/architecture.md`
- Monolith deploy/runtime defaults: `docs/deploy_three_layer_runtime.md`

## Product frame

CalendarDIFF is not a general course-message classifier.

It exists to maintain a canonical backend event-time database for grade-relevant academic events and decide whether a new signal implies:

1. a new event
2. a meaningful time change
3. no effective change
4. or a change that must be reviewed safely

Default stance:

- be conservative
- prefer `unknown` over false positive deadline changes
- ignore noisy course-related mail without an explicit actionable time signal

## Working model

Keep these invariants intact:

- Stable identity: `entity_uid` is the only stable internal identity.
- Canonical state: approved user-visible event state lives only in `event_entities`.
- Facts layer: `input_sources` and `source_event_observations` are source facts, not canonical identity.
- Proposal layer: `changes` is the semantic proposal queue and audit log.
- Projection layer: user-facing display should prefer `course + family + ordinal`, but that is display only.
- Evidence: review evidence must be frozen on `changes`; do not make preview depend on files, secrets, cursors, or live observations.

## Current runtime and route assumptions

Default runtime is one monolith backend process.

Do not reintroduce split-service defaults, service-specific OpenAPI snapshots, or internal-service token workflows into the main repo path.

Current public route families are:

- `/auth/*`
- `/profile/me`
- `/sources/*`
- `/onboarding/*`
- `/review/*`
- `/events/manual*`
- `/health`

Additional route rules:

- family/raw-type management lives under `/review/course-work-item-*`
- `/users/*` is not an active public route family

## Workflow

When handling a task, first restate it in product terms:

- what grade-relevant time signal or canonical-state behavior changes?
- which layer is touched: facts, proposal, approved state, projection, or docs/contracts?
- what user-visible or review-visible effect should change?

Then classify the change:

1. Facts extraction: Gmail/ICS parsing, observation shape, source facts.
2. Proposal logic: proposal rebuild, diffing, change creation, source linking.
3. Approved state: review approve/reject, canonical edit, manual event mutation.
4. Projection/API: review DTOs, profile/events/review routes, OpenAPI, frontend callers.
5. Docs/contracts cleanup: remove stale language that contradicts current semantics or monolith defaults.

## Guardrails

Stop and call it out if a change would reintroduce any of these patterns:

- treating source IDs or `course + family + ordinal` as stable canonical identity
- putting approved user-visible state anywhere other than `event_entities`
- using `changes` as an old `Input/Event` compatibility shim instead of semantic proposals
- reviving `/users/*` as current public API
- reviving split-service default runtime, internal metrics auth, or multi-service compose defaults
- describing `inputs`, `events`, `snapshots`, or `snapshot_events` as active canonical tables
- making review evidence depend on filesystem paths or live source state
- widening detection to generic course chatter instead of explicit grade-relevant time signals

## Validation

Run the smallest relevant checks first. For core semantic changes, prefer targeted backend tests before broad suites.

Useful baselines:

```bash
pytest tests/test_review_*.py \
  tests/test_manual_events_api.py \
  tests/test_course_work_item_families_api.py \
  tests/test_course_raw_types_api.py \
  tests/test_users_timezone_api.py \
  tests/test_openapi_contract_snapshots.py \
  tests/test_runtime_entrypoints.py
```

If parser/apply logic changed, add the relevant Gmail / ICS tests.

If frontend DTO consumption or routes changed:

```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```

If OpenAPI changed:

```bash
python scripts/update_openapi_snapshots.py
```
