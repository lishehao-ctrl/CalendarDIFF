# Backend Remove Link Alert Layer Spec

## 1. Purpose

This backend-only pass removes the `EventLinkAlert` layer from CalendarDIFF.

The current linker governance model has three separate queues:

1. accepted links: `event_entity_links`
2. candidate links: `event_link_candidates`
3. medium-risk alert links: `event_link_alerts`

For the long-term goal of multi-source CalendarDIFF, the third queue is unnecessary architecture weight.

It adds:

- a separate table
- separate enums and services
- separate outbox event family
- separate consumer tick
- separate API surface
- separate summary/metrics logic

without representing a truly different product state than “accepted link” or “needs review”.

This pass removes that third governance layer and converges link behavior to:

- accepted links live only in `event_entity_links`
- uncertain link decisions live only in `event_link_candidates`
- rejected source/entity pairs live only in `event_link_blocks`

Frontend is explicitly out of scope for this pass.

## 2. Fixed Product and Runtime Decisions

These decisions are already made for this pass.

### 2.1 Link governance is two-lane, not three-lane

After this pass, link governance has only these states:

1. accepted: `event_entity_links`
2. review-needed: `event_link_candidates`

`event_link_alerts` is removed completely.

### 2.2 Auto-linked records without canonical pending no longer open an alert queue

If an auto-link occurs and no canonical pending change is created:

- do not create a separate alert record
- do not enqueue any link-alert outbox event
- keep only the accepted link state

This is intentionally a simplification, not a replacement with another queue.

### 2.3 Candidate opening no longer resolves alert state

Because alerts are being removed:

- candidate creation should no longer emit “resolve alert for pair”
- canonical pending creation should no longer emit “resolve alerts for entities”
- link delete/relink should no longer resolve alert rows

All alert-resolution side effects must be deleted with the alert layer.

### 2.4 Backend-only pass

Do not modify frontend files in this pass.

If backend API contracts shrink and temporarily break the current frontend, that is acceptable for this pass.

## 3. Required End State

After this pass:

- there is no `EventLinkAlert` runtime model
- there is no `event_link_alerts` table in the active model baseline
- there are no link-alert outbox event types
- there is no link-alert consumer tick
- there are no `/review/link-alerts/*` backend routes
- `/review/summary` no longer exposes `link_alerts_pending`
- review/internal metrics no longer expose link-alert metrics

The remaining link architecture is:

- `event_entity_links`
- `event_link_candidates`
- `event_link_blocks`

## 4. Required Implementation Areas

Likely backend files/modules:

- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/db/models/review.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/db/models/input.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/db/models/shared.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/db/models/__init__.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/apply.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/linking_engine.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/pending_auto_link_alerts.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/link_alert_outbox.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/router.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/summary_service.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/schemas.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/alerts_router.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/alerts_query_service.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/alerts_decision_service.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/alerts_upsert_service.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/alerts_event_consumer.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/links_service.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/metrics_router.py`
- backend docs describing review/link runtime behavior
- backend tests that currently assert link-alert behavior

The executing agent may delete modules entirely when they become dead.

## 5. Required Runtime Rules

### 5.1 Auto-link path rule

When Gmail linking deterministically resolves to an accepted entity and no canonical pending change is created:

- keep the accepted `event_entity_link`
- do not create `event_link_alert`
- do not emit any alert-related outbox event

### 5.2 Candidate path rule

When link review is needed:

- use only `event_link_candidates`
- do not also create or resolve link-alert state

### 5.3 Link mutation rule

When links are deleted or relinked manually:

- mutate links and blocks/candidates as needed
- do not attempt to resolve or update alert state

### 5.4 Summary and metrics rule

Review summary and review internal metrics must stop counting alert-specific state.

## 6. Acceptance Criteria

This pass is complete when all of the following are true:

1. `EventLinkAlert` model and related enums are removed from active backend runtime
2. all alert-only modules are removed or made unreachable because they are dead
3. `apply.py`, `linking_engine.py`, and `links_service.py` no longer emit or resolve alert-related side effects
4. `/review/link-alerts/*` routes are removed from backend routing
5. `/review/summary` no longer returns `link_alerts_pending`
6. internal review metrics no longer include link-alert counters
7. link behavior still supports accepted links, candidate review, and blocks
8. frontend remains untouched

## 7. Required Tests

At minimum, update tests for:

1. review summary without `link_alerts_pending`
2. link candidate flows continue to work without alert side effects
3. link delete/relink flows continue to work without alert side effects
4. alert-specific backend tests are deleted or rewritten because the layer no longer exists
5. pending/apply boundary tests are updated to no longer expect alert modules/events

Likely test areas:

- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/test_review_items_summary_api.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/test_review_link_candidates_api.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/test_review_link_alerts_api.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/test_review_link_alert_events_consumer.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/test_core_ingest_pending_boundaries.py`

Alert-specific tests should be removed if they only verify deleted behavior.

## 8. Explicit Non-Goals

Do not do these in this pass:

- frontend updates
- inventing a replacement alert queue
- redesigning candidate scoring logic
- redesigning notification behavior
- broad review DTO cleanup beyond what is required by removing alerts

## 9. Validation

The executing agent should derive its exact command list from the final diff, but validation must include:

- targeted backend pytest for review summary, link candidates, link/link-delete flows, and any touched ingest boundary tests
- compile/import sanity for changed backend modules

This is a backend-only pass; frontend files should remain untouched.
