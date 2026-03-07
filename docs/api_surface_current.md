# API Surface Snapshot (Current, V2, Multi-Service)

This document captures active HTTP APIs after microservice split with shared PostgreSQL.

## Service Endpoints

1. input-service: `http://localhost:8201`
2. ingest-service: `http://localhost:8202`
3. llm-service: `http://localhost:8205`
4. review-service: `http://localhost:8200`
5. notification-service: `http://localhost:8204`

Default compose exposure:

1. external: input-service + review-service
2. internal-only: ingest-service + llm-service + notification-service

## input-service (public)

### Workspace

1. `GET /health`

### Onboarding + User

1. `GET /onboarding/status`
2. `POST /onboarding/registrations`
3. `GET /users/me`
4. `PATCH /users/me`

User profile includes:

1. `timezone_name` (IANA timezone, default `UTC`)

### Input Sources + Sync

1. `POST /sources`
2. `GET /sources`
3. `PATCH /sources/{source_id}`
4. `DELETE /sources/{source_id}`
5. `POST /sources/{source_id}/sync-requests`
6. `GET /sync-requests/{request_id}`
7. `POST /sources/{source_id}/oauth-sessions`
8. `GET /oauth/callbacks/{provider}`
9. `POST /sources/{source_id}/webhooks/{provider}`
10. `GET /internal/metrics` (internal token auth)

## ingest-service (internal ops + worker)

1. `GET /health`
2. `POST /internal/ingest/jobs/{job_id}/replays`
3. `POST /internal/ingest/jobs/dead-letter/replays`
4. `GET /internal/metrics`

Runtime responsibilities:

1. orchestrator tick
2. connector tick (`gmail` incremental fetch, `ics` delta parser)
3. enqueue llm parse tasks to Redis only for changed payloads
4. emits `ingest.result.ready`
5. worker lifecycle runs under app lifespan via AnyIO task groups (no per-service thread starter)

## llm-service (internal worker + metrics)

1. `GET /health`
2. `GET /internal/metrics`

Runtime responsibilities:

1. consume Redis stream tasks
2. execute LLM parser calls with global limiter
3. process ICS removed delta records without LLM call
4. manage retry zset and backoff
5. write `ingest_results` and emit `ingest.result.ready`
6. worker lifecycle runs under app lifespan via AnyIO task groups (no per-service thread starter)

## review-service (read/review + internal apply)

1. `GET /health`
2. `GET /review/summary`
3. `GET /review/changes`
4. `PATCH /review/changes/{change_id}/views`
5. `POST /review/changes/{change_id}/decisions`
6. `GET /review/changes/{change_id}/evidence/{side}/preview`
7. `POST /review/corrections/preview`
8. `POST /review/corrections`
9. `GET /review/link-candidates`
10. `POST /review/link-candidates/{id}/decisions`
11. `POST /review/link-candidates/batch/decisions`
12. `GET /review/link-candidates/blocks`
13. `DELETE /review/link-candidates/blocks/{block_id}`
14. `GET /review/links`
15. `DELETE /review/links/{link_id}`
16. `POST /review/links/relink`
17. `GET /review/link-alerts`
18. `POST /review/link-alerts/{alert_id}/dismiss`
19. `POST /review/link-alerts/{alert_id}/mark-safe`
20. `POST /review/link-alerts/batch/decisions`
21. `POST /internal/review/ingest-results/applications`
22. `GET /internal/review/ingest-results/{request_id}`
23. `GET /internal/metrics`

Notes:

1. review-service consumes `ingest.result.ready` and emits `review.pending.created`
2. approve mutates canonical events; reject does not
3. manual correction mutates canonical events directly and writes an approved audit change
4. manual correction does not emit `review.pending.created` (no notification enqueue)
5. link-candidate generation/decisions are parallel linker governance flow and do not emit `review.pending.created`
6. link-alert queue is medium-risk, non-blocking, and only stores `auto-link` records that produced no canonical pending change in the same apply round
7. `GET /review/summary` returns pending counts only (`changes`, `link-candidates`, `link-alerts`) for top-level badge rendering
8. batch decision endpoints are partial-success by design and return per-item results:
   - `POST /review/link-candidates/batch/decisions`
   - `POST /review/link-alerts/batch/decisions`

## notification-service (internal ops + worker)

1. `GET /health`
2. `GET /internal/notifications/status`
3. `GET /internal/metrics`

Runtime responsibilities:

1. consumes `review.pending.created`
2. enqueues `notifications`
3. processes digest sends (`digest_send_log`)
4. worker lifecycle runs under app lifespan via AnyIO task groups (no per-service thread starter)

## Event Contracts

1. `sync.requested` (input -> ingest)
2. `ingest.result.ready` (ingest -> review)
3. `review.pending.created` (review -> notification)
4. `review.decision.approved|rejected` (review audit)

See `docs/event_contracts.md`.

## Internal Auth Contract

All `/internal/*` endpoints require:

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
