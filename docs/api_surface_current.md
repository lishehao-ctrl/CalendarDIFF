# API Surface Snapshot (Current Multi-Service Runtime)

This document captures the active HTTP APIs after the microservice split with shared PostgreSQL.

## Service Endpoints

Direct-run local defaults:

1. public-service: `http://localhost:8200`
2. input-service: `http://localhost:8201`
3. ingest-service: `http://localhost:8202`
4. review-service: `http://localhost:8203`
5. llm-service: `http://localhost:8205`
6. notification-service: `http://localhost:8204`

Default compose exposure:

1. external: public-service
2. internal-only: input-service + review-service + ingest-service + llm-service + notification-service
3. compose public host port remains `8000 -> public-service`

## public-service (public gateway)

Public gateway currently aggregates user-facing auth, onboarding, sources, review changes, and link review APIs into one contract for the frontend.

## input-service (internal/public-compatible)

### Workspace

1. `GET /health`

### Auth

1. `POST /auth/register`
2. `POST /auth/login`
3. `POST /auth/logout`
4. `GET /auth/session`

Session model:

1. browser session uses HttpOnly cookie
2. dashboard-facing requests still pass through frontend proxy with `X-API-Key`
3. public APIs are scoped to the authenticated current user

### Onboarding + User

1. `GET /onboarding/status`
2. `POST /onboarding/registrations`
3. `GET /users/me`
4. `PATCH /users/me`

Current onboarding status shape includes:

1. `stage`
2. `message`
3. `registered_user_id`
4. `first_source_id`
5. `source_health`

`source_health` includes:

1. `status` (`healthy | attention | disconnected`)
2. `message`
3. `affected_source_id`
4. `affected_provider`

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

Current source semantics:

1. `provider=gmail` is single-source per user
2. `provider=ics` is single Canvas ICS link per user
3. Canvas ICS create/update is URL-driven; the frontend no longer collects `source_key` or `display_name`
4. `GET /sources` still returns `source_key` and `display_name`, but Canvas ICS is normalized to fixed values

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
5. worker lifecycle runs under app lifespan via AnyIO task groups

## llm-service (internal worker + metrics)

1. `GET /health`
2. `GET /internal/metrics`

Runtime responsibilities:

1. consume Redis stream tasks
2. execute LLM parser calls with global limiter
3. process ICS removed delta records without LLM call
4. manage retry zset and backoff
5. write `ingest_results` and emit `ingest.result.ready`
6. worker lifecycle runs under app lifespan via AnyIO task groups

## review-service (read/review + internal apply)

1. `GET /health`
2. `GET /review/summary`
3. `GET /review/changes`
4. `PATCH /review/changes/{change_id}/views`
5. `POST /review/changes/{change_id}/decisions`
6. `GET /review/changes/{change_id}/evidence/{side}/preview`
7. `POST /review/changes/batch/decisions`
8. `POST /review/edits/preview`
9. `POST /review/edits`
10. `GET /review/link-candidates`
11. `POST /review/link-candidates/{id}/decisions`
12. `POST /review/link-candidates/batch/decisions`
13. `GET /review/link-candidates/blocks`
14. `DELETE /review/link-candidates/blocks/{block_id}`
15. `GET /review/links`
16. `DELETE /review/links/{link_id}`
17. `POST /review/links/relink`
18. `POST /internal/review/ingest-results/applications`
19. `GET /internal/review/ingest-results/{request_id}`
20. `GET /internal/metrics`

Notes:

1. review-service consumes `ingest.result.ready` and emits `review.pending.created`
2. approve mutates approved semantic state in `event_entities`; reject does not
3. unified edits split proposal edits (`mode=proposal`) from direct canonical edits (`mode=canonical`)
4. link governance uses two lanes: accepted links in `event_entity_links`, review-needed links in `event_link_candidates`
5. `GET /review/summary` returns pending counts for `changes` and `link-candidates`

## notification-service (internal ops + worker)

1. `GET /health`
2. `GET /internal/notifications/status`
3. `GET /internal/metrics`

Runtime responsibilities:

1. consumes `review.pending.created`
2. enqueues `notifications`
3. processes digest sends (`digest_send_log`)
4. worker lifecycle runs under app lifespan via AnyIO task groups

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

1. parser implementation lives in shared modules used by ingest + llm flows
2. parser runtime service is `llm-service`
3. protocol is OpenAI-compatible `chat/completions`
4. ICS parser contract uses `calendar_delta` payloads for changed VEVENT components only
5. canonical/enrichment split keeps canonical fields deterministic and enrichment LLM-derived
6. parser payload contract is fixed at `obs_v3`
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
