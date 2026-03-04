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

## 2) `ingest.result.ready` (llm -> review)

Producer: llm-service worker  
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
    "reviewed_at": "2026-03-02T12:34:56+00:00",
    "decision_origin": "review_api|manual_correction",
    "correction_change_id": 901,
    "rejected_pending_change_ids": [887, 888]
  }
}
```

## Compatibility Rules

1. Additive payload changes only.
2. Existing keys are immutable in meaning.
3. Consumers must ignore unknown fields.
4. Event type names are immutable once published.

## Internal Ingest Record Envelope (Non-Outbox, additive)

The `ingest_results.records[*].payload` envelope used between llm/review runtime keeps record types stable and adds layered fields:

1. hard-cut parser schema version: `enrichment.payload_schema_version = "obs_v3"` (required).
2. `source_canonical`: deterministic source fields used for canonical diff and pending generation.
3. `enrichment`: LLM-derived metadata (`course_parse`, `event_parts`, `link_signals`). No local regex/raw-text fallback is used for these fields.
4. additive linker signals:
   - Gmail canonical signals: `from_header`, `thread_id`, `internal_date`
   - ICS canonical signals: `organizer`
   - enrichment signals: `enrichment.link_signals` (`keywords`, `exam_sequence`, `location_text`, `instructor_hint`)

Parser note:

1. `course_parse` must be schema-valid from LLM output; invalid/missing objects are treated as parser failures (retry/dead-letter path), not downgraded by local inference.
2. `event_parts` and `link_signals` are also required and schema-validated; missing/invalid objects fail the parser output.
3. link-candidate review flow is storage/API-only (`event_link_candidates` + `/v2/review-items/link-candidates*`) and does not emit outbox notification events.

Example (`calendar.event.extracted`):

```json
{
  "payload": {
    "source_canonical": {
      "external_event_id": "uid#rid",
      "source_title": "CSE 151A exam 1",
      "source_dtstart_utc": "2026-03-10T20:00:00+00:00",
      "source_dtend_utc": "2026-03-10T21:00:00+00:00"
    },
    "enrichment": {
      "course_parse": {
        "dept": "CSE",
        "number": 151,
        "suffix": "A",
        "quarter": "WI",
        "year2": 26,
        "confidence": 0.95,
        "evidence": "CSE 151A WI26"
      },
      "event_parts": {
        "type": "exam",
        "index": 1,
        "qualifier": null,
        "confidence": 0.94,
        "evidence": "exam 1"
      },
      "link_signals": {
        "keywords": ["exam"],
        "exam_sequence": 1,
        "location_text": "Center Hall 101",
        "instructor_hint": "Prof Alice"
      },
      "payload_schema_version": "obs_v3"
    }
  }
}
```
