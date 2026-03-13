# Event Contracts (Postgres Outbox/Inbox)

This document defines runtime outbox/inbox payloads used between microservices in shared PostgreSQL stage.

## 1) `sync.requested` (input -> ingest)

Producer: input-service  
Consumer: ingest-service orchestrator (`orchestrator.sync_requested`)

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
Consumer: review-service apply worker (`core.ingest.apply`)

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
Consumer: notification-service enqueue consumer (`notification.review_pending_created`)

```json
{
  "event_type": "review.pending.created",
  "aggregate_type": "change_batch",
  "aggregate_id": "<first_change_id>",
  "payload": {
    "user_id": 88,
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
    "entity_uid": "mk_...",
    "review_status": "approved",
    "reviewed_by_user_id": 1,
    "reviewed_at": "2026-03-02T12:34:56+00:00",
    "decision_origin": "review_api|canonical_edit",
    "canonical_edit_change_id": 901,
    "rejected_pending_change_ids": [887, 888]
  }
}
```

## Compatibility Rules

1. Additive payload changes only.
2. Existing keys are immutable in meaning.
3. Consumers must ignore unknown fields.
4. Event type names are immutable once published.
5. Family label authority is explicit:
   - `family_id` is the only label authority
   - user-facing display resolves latest `course_work_item_label_families.canonical_label` by `family_id`
   - `changes.family_name` may remain frozen audit payload text and is not default display authority
   - missing `family_id` or unresolved family-row label authority is treated as a runtime data-integrity error, not a normal fallback case
6. Family lifecycle policy is non-destructive for normal product flows:
   - family rows are not a normal hard-delete target
   - update/relink flows remain authoritative for user-facing management
7. Missing course identity handling is ingest-side isolation:
   - record is persisted in `ingest_unresolved_records`
   - record is excluded from normal `source_event_observations -> changes -> review.pending.created` path

## Internal Ingest Record Envelope (Non-Outbox, additive)

The parser-stage `ingest_results.records[*].payload` envelope used between llm/review runtime keeps record types stable:

1. `source_facts`: deterministic source fields used for semantic proposal diff and pending generation.
2. `semantic_event_draft`: parser-stage semantic payload (required on extracted records).
3. `link_signals`: parser-stage linking signals (required on extracted records).
4. Gmail extracted records also include `message_id` (required).
5. parser-stage `semantic_event_draft` is normalized in apply/runtime into observation `semantic_event`.

Runtime observation envelope (`source_event_observations.event_payload`) is fixed to:

1. `source_facts`
2. `semantic_event`
3. `link_signals`
4. `kind_resolution`

Unresolved note:

1. If a record cannot resolve course identity, it is stored in `ingest_unresolved_records` and does not upsert `source_event_observations`.
2. Unresolved records do not create pending `changes` and do not emit `review.pending.created`.

Parser note:

1. `semantic_event_draft` must be schema-valid from parser output; invalid/missing objects are treated as parser failures (retry/dead-letter path), not downgraded by local inference.
2. `link_signals` is required and schema-validated; missing/invalid objects fail parser output.
3. link-candidate review flow is storage/API-only (`event_link_candidates` + `/review/link-candidates*`) and does not emit outbox notification events.
4. accepted links are persisted in `event_entity_links`; uncertain linking decisions are persisted in `event_link_candidates`.

Example (`calendar.event.extracted`):

```json
{
  "payload": {
    "source_facts": {
      "external_event_id": "uid#rid",
      "source_title": "CSE 151A exam 1",
      "source_dtstart_utc": "2026-03-10T20:00:00+00:00",
      "source_dtend_utc": "2026-03-10T21:00:00+00:00"
    },
    "semantic_event_draft": {
      "course_dept": "CSE",
      "course_number": 151,
      "course_suffix": "A",
      "course_quarter": "WI",
      "course_year2": 26,
      "raw_type": "exam",
      "event_name": "Exam 1",
      "ordinal": 1,
      "due_date": "2026-03-10",
      "due_time": "20:00:00",
      "time_precision": "datetime",
      "confidence": 0.95,
      "evidence": "CSE 151A exam 1"
    },
    "link_signals": {
      "keywords": ["exam"],
      "exam_sequence": 1,
      "location_text": "Center Hall 101",
      "instructor_hint": "Prof Alice"
    }
  }
}
```
