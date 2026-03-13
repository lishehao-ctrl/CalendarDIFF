# Backend Unresolved Transition Spec

## 1. Purpose

This backend-only pass fixes the remaining state-transition bug in the unresolved ingest flow.

The previous pass correctly introduced an unresolved ingest bucket and enforced `family_id` as a hard invariant for normal reviewable events.
However, a previously valid source record can still keep an old active `source_event_observation` after a later ingest for the same `source_id + external_event_id` becomes unresolved.

That stale active observation must no longer remain in the normal active observation set.

Frontend is explicitly out of scope for this pass.

## 2. Fixed Product and Runtime Decisions

These decisions are already made.

### 2.1 Unresolved is an ingest-isolation state, not a review state

If a record cannot resolve course identity:

- it belongs only in the unresolved ingest bucket
- it must not be represented as a normal active observation
- it must not generate new review changes
- it must not emit `review.pending.created`

### 2.2 `valid -> unresolved` is not a semantic removal event

When a previously valid source record later becomes unresolved:

- the old active observation must be retired from the active observation set
- this transition must not create a new semantic proposal by itself
- this transition must not generate a synthetic `removed` or `due_changed` change just because course identity became unavailable

Parser uncertainty is not the same thing as a real source removal.

### 2.3 Later recovery still restores normal flow

If a later ingest for the same source record becomes valid again:

- unresolved state may be resolved/superseded as before
- a normal active observation may be recreated or reactivated
- normal proposal generation may resume from that later valid state

### 2.4 Backend-only pass

Do not modify frontend files in this pass.

## 3. Required End State

For both calendar and Gmail apply paths:

- a fresh unresolved record creates only unresolved ingest state
- a later valid record resolves unresolved ingest state and resumes normal observation flow
- a later unresolved record for the same source/external id retires any prior active observation for that source record
- the later unresolved transition does not create additional `changes`
- the later unresolved transition does not emit `review.pending.created`

After this pass, there must not be any normal active `SourceEventObservation` row left behind for a source record whose latest ingest state is unresolved.

## 4. Required Runtime Rules

### 4.1 Transition isolation rule

If `source_id + external_event_id` currently has an active normal observation and the new ingest result for that same source record is unresolved:

- the prior active observation must be marked inactive, retired, or otherwise removed from the active set
- the unresolved ingest row must become the active representation of that source record

### 4.2 No semantic side-effect rule

The transition above must not:

- create a new pending `Change`
- emit `review.pending.created`
- trigger a semantic removal solely because the ingest record became unresolved

### 4.3 Calendar full-sync rule

For calendar apply specifically:

- unresolved external ids must not be treated as “seen and still active” in a way that preserves the stale observation
- the full-sync active-row sweep must not leave the prior active observation alive for an unresolved record

### 4.4 Gmail incremental rule

For Gmail apply specifically:

- unresolved transition handling must explicitly retire the prior active observation for the same source/external id
- this must happen even though Gmail apply does not use the calendar full-sync sweep path

## 5. Required Implementation Areas

Likely backend files:

- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/calendar_apply.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/gmail_apply.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/unresolved_store.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/observation_store.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/pending_proposal_rebuild.py` only if needed to preserve the “no semantic side-effect” invariant
- targeted backend docs if behavior wording changes

The executing agent may introduce a small helper for “retire active observation for unresolved transition” if that keeps the logic shared and explicit.

## 6. Acceptance Criteria

This pass is complete when all of the following are true:

1. calendar `valid -> unresolved` retires the prior active observation for that source record
2. Gmail `valid -> unresolved` retires the prior active observation for that source record
3. the transition above does not increase `Change` count
4. the transition above does not emit `review.pending.created`
5. unresolved bucket behavior from the previous pass still works for fresh unresolved and unresolved -> valid recovery
6. frontend remains untouched

## 7. Required Tests

At minimum, add or update tests for:

1. calendar `valid -> unresolved` for the same `external_event_id`
   - active observation count becomes `0` for that source record
   - no additional `Change` rows are created by the unresolved transition
   - no additional `review.pending.created` outbox events are emitted by the unresolved transition
2. Gmail `valid -> unresolved` for the same `external_event_id`
   - active observation count becomes `0` for that source record
   - no additional `Change` rows are created by the unresolved transition
   - no additional `review.pending.created` outbox events are emitted by the unresolved transition
3. previously added unresolved tests still pass:
   - fresh unresolved isolation
   - unresolved -> valid recovery
   - calendar removed-record unresolved cleanup

Likely test file:

- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/test_core_ingest_unresolved_bucket.py`

Additional targeted updates may be needed in:

- calendar apply tests
- outbox contract tests

## 8. Explicit Non-Goals

Do not do these in this pass:

- frontend updates
- broad review/change semantics redesign
- digest failure-granularity work
- general payload-contract cleanup unrelated to this transition bug
- unresolved user-facing APIs or UI

## 9. Validation

The executing agent should derive its own exact commands from the final diff, but validation must include:

- targeted backend pytest for unresolved bucket and affected ingest flows
- compile/import sanity for changed backend modules

This is a backend-only pass; frontend files should remain untouched.
