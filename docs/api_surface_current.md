# API Surface Snapshot (Current, V2, Multi-Service)

This document captures active HTTP APIs after microservice split with shared PostgreSQL.

## Service Endpoints

1. input-service: `http://localhost:8001`
2. ingest-service: `http://localhost:8002`
3. llm-service: `http://localhost:8005`
4. review-service: `http://localhost:8000`
5. notification-service: `http://localhost:8004`

Default compose exposure:

1. external: input-service + review-service
2. internal-only: ingest-service + llm-service + notification-service

## input-service (`/v2` public)

### Workspace

1. `GET /health`

### Onboarding + User

1. `GET /v2/onboarding/status`
2. `POST /v2/onboarding/registrations`
3. `GET /v2/users/me`
4. `PATCH /v2/users/me`

User profile includes:

1. `timezone_name` (IANA timezone, default `UTC`)

### Input Sources + Sync

1. `POST /v2/input-sources`
2. `GET /v2/input-sources`
3. `PATCH /v2/input-sources/{source_id}`
4. `DELETE /v2/input-sources/{source_id}`
5. `POST /v2/sync-requests`
6. `GET /v2/sync-requests/{request_id}`
7. `POST /v2/oauth-sessions`
8. `GET /v2/oauth-callbacks/{provider}`
9. `POST /v2/webhook-events/{source_id}/{provider}`
10. `GET /internal/v2/metrics` (internal token auth)

## ingest-service (`/internal/v2` ops + worker)

1. `GET /health`
2. `POST /internal/v2/ingest-jobs/{job_id}/replays`
3. `POST /internal/v2/ingest-jobs/dead-letter/replays`
4. `GET /internal/v2/metrics`

Runtime responsibilities:

1. orchestrator tick
2. connector tick (`gmail` incremental fetch, `ics` delta parser)
3. enqueue llm parse tasks to Redis only for changed payloads
4. emits `ingest.result.ready`

## llm-service (`/internal/v2` worker + metrics)

1. `GET /health`
2. `GET /internal/v2/metrics`

Runtime responsibilities:

1. consume Redis stream tasks
2. execute LLM parser calls with global limiter
3. process ICS removed delta records without LLM call
4. manage retry zset and backoff
5. write `ingest_results` and emit `ingest.result.ready`

## review-service (`/v2` read/review + internal apply)

1. `GET /health`
2. `GET /v2/review-items/emails`
3. `PATCH /v2/review-items/emails/{email_id}`
4. `POST /v2/review-items/emails/{email_id}/views`
5. `GET /v2/review-items/changes`
6. `PATCH /v2/review-items/changes/{change_id}/views`
7. `POST /v2/review-items/changes/{change_id}/decisions`
8. `GET /v2/review-items/changes/{change_id}/evidence/{side}/preview`
9. `POST /v2/review-items/changes/corrections/preview`
10. `POST /v2/review-items/changes/corrections`
11. `GET /v2/review-items/link-candidates`
12. `POST /v2/review-items/link-candidates/{id}/decisions`
13. `GET /v2/review-items/link-candidates/blocks`
14. `DELETE /v2/review-items/link-candidates/blocks/{block_id}`
15. `GET /v2/review-items/links`
16. `DELETE /v2/review-items/links/{link_id}`
17. `POST /v2/review-items/links/relink`
18. `GET /v2/review-items/link-alerts`
19. `POST /v2/review-items/link-alerts/{alert_id}/dismiss`
20. `POST /v2/review-items/link-alerts/{alert_id}/mark-safe`
21. `GET /v2/timeline-events`
22. `POST /internal/v2/ingest-results/applications`
23. `GET /internal/v2/ingest-results/{request_id}`
24. `GET /internal/v2/metrics`

Notes:

1. review-service consumes `ingest.result.ready` and emits `review.pending.created`
2. approve mutates canonical events; reject does not
3. manual correction mutates canonical events directly and writes an approved audit change
4. manual correction does not emit `review.pending.created` (no notification enqueue)
5. link-candidate generation/decisions are parallel linker governance flow and do not emit `review.pending.created`
6. link-alert queue is medium-risk, non-blocking, and only stores `auto-link` records that produced no canonical pending change in the same apply round

## notification-service (`/internal/v2` ops + worker)

1. `GET /health`
2. `GET /internal/v2/notification/status`
3. `GET /internal/v2/metrics`

Runtime responsibilities:

1. consumes `review.pending.created`
2. enqueues `notifications`
3. processes digest sends (`digest_send_log`)

## Event Contracts

1. `sync.requested` (input -> ingest)
2. `ingest.result.ready` (ingest -> review)
3. `review.pending.created` (review -> notification)
4. `review.decision.approved|rejected` (review audit)

See `docs/event_contracts.md`.

## Internal Auth Contract

All `/internal/v2/*` endpoints require:

1. `X-Service-Name: <input|ingest|review|notification|ops>`
2. `X-Service-Token: <matching token from INTERNAL_SERVICE_TOKEN_*>`

## LLM Runtime

1. parser location: ingest-service
2. parser runtime service: llm-service
3. protocol: OpenAI-compatible `chat/completions`
4. ICS parser contract: connector emits `calendar_delta_v1` payload, llm-service only parses changed VEVENT components
5. canonical/enrichment split: payloads include `source_canonical` (deterministic) and `enrichment` (LLM/rule metadata)
6. parser payload contract is hard-cut to `obs_v3`:
   - calendar payload: `source_canonical` + `enrichment(course_parse,event_parts,link_signals,payload_schema_version)`
   - gmail payload: `message_id` + `source_canonical` + `enrichment(course_parse,event_parts,link_signals,payload_schema_version)`
7. ICS canonical fields come from parser/source; LLM output remains enrichment-only (no canonical fallback fields)
7. env:
   - `INGESTION_LLM_MODEL`
   - `INGESTION_LLM_BASE_URL`
   - `INGESTION_LLM_API_KEY`
   - `REDIS_URL`
   - `LLM_RATE_LIMIT_TARGET_RPS`
   - `LLM_RATE_LIMIT_HARD_RPS`
   - optional fake-source overrides:
     - `GMAIL_API_BASE_URL`
     - `GMAIL_OAUTH_TOKEN_URL`
     - `GMAIL_OAUTH_AUTHORIZE_URL`

## OpenAPI Contract Snapshots

Update snapshots:

```bash
python scripts/update_openapi_snapshots.py
```
