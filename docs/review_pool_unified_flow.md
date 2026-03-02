# Unified Review Pool Flow

## Status lifecycle

1. Ingestion parsers emit records (`calendar.event.extracted`, `gmail.message.extracted`).
2. Core apply converts records into `source_event_observations`.
3. Apply computes merged candidates by `merge_key` and creates `changes.review_status=pending` proposals.
4. Pending proposal creation enqueues notification.
5. Reviewer decides with `approve` or `reject`.
6. `approve` applies canonical event mutation; `reject` leaves canonical unchanged.

## APIs

1. `GET /v2/review-items/changes`
2. `PATCH /v2/review-items/changes/{change_id}/views`
3. `POST /v2/review-items/changes/{change_id}/decisions`

## Decision semantics

1. `approve`
   - `created`: insert canonical event if missing
   - `due_changed`: update canonical event
   - `removed`: delete canonical event
   - set `changes.review_status=approved`
2. `reject`
   - no canonical event mutation
   - set `changes.review_status=rejected`

## Compatibility notes

1. `GET /v2/change-events` returns approved changes by default.
2. `GET /v2/timeline-events` returns canonical applied events only.
3. `POST /v2/review-items/emails/{email_id}/applications` is deprecated and returns migration guidance.
