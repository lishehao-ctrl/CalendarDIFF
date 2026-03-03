# Event Contracts (Postgres Outbox/Inbox)

This document defines canonical event payloads used between microservices in shared PostgreSQL stage.

## 1) `sync.requested` (input -> ingest)

Producer: input-service  
Consumer: ingest-service orchestrator (`orchestrator.sync_requested.v1`)

```json
{
  "event_type": "sync.requested",
  "aggregate_type": "sync_request",
  "aggregate_id": "<request_id>",
  "payload": {
    "request_id": "<request_id>",
    "source_id": 123,
    "provider": "gmail|ics",
    "trigger_type": "manual|scheduler|webhook"
  }
}
```

## 2) `ingest.result.ready` (ingest -> review)

Producer: ingest-service connector runtime  
Consumer: review-service apply worker (`core.ingest.apply.v1`)

```json
{
  "event_type": "ingest.result.ready",
  "aggregate_type": "ingest_result",
  "aggregate_id": "<request_id>",
  "payload": {
    "request_id": "<request_id>",
    "source_id": 123,
    "provider": "gmail|ics",
    "status": "CHANGED|NO_CHANGE|FETCH_FAILED|PARSE_FAILED|AUTH_FAILED|RATE_LIMITED"
  }
}
```

## 3) `review.pending.created` (review -> notification)

Producer: review-service core apply  
Consumer: notification-service enqueue consumer (`notification.review_pending_created.v1`)

```json
{
  "event_type": "review.pending.created",
  "aggregate_type": "change_batch",
  "aggregate_id": "<first_change_id>",
  "payload": {
    "input_id": 88,
    "change_ids": [901, 902],
    "deliver_after": "2026-03-02T12:34:56+00:00"
  }
}
```

## 4) `review.decision.approved|rejected` (review audit)

Producer: review-service review decision API  
Consumers: optional observability/audit services

```json
{
  "event_type": "review.decision.approved",
  "aggregate_type": "change",
  "aggregate_id": "901",
  "payload": {
    "change_id": 901,
    "event_uid": "mk_...",
    "review_status": "approved",
    "reviewed_by_user_id": 1,
    "reviewed_at": "2026-03-02T12:34:56+00:00"
  }
}
```

## Compatibility Rules

1. Additive payload changes only.
2. Existing keys are immutable in meaning.
3. Consumers must ignore unknown fields.
4. Event type names are immutable once published.
