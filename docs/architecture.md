# CalendarDIFF Architecture (Three-Layer Runtime)

## 1) Runtime Topology

Current deployment is hard-cut to four containers/processes:

1. `api` (`uvicorn app.main:app`) - the only HTTP entrypoint
2. `ingestion-worker` (`python -m services.ingestion_runtime.worker`)
3. `notification-worker` (`python -m services.notification.worker`)
4. `postgres`

Removed from runtime:

1. split `core-api` / `input-control-plane-api`
2. nginx gateway proxy
3. separate orchestrator/connector/core-apply worker entrypoints
4. legacy scheduler service runtime

## 2) Layer Responsibilities

### Layer 1: Input (Ingestion)

Owned by `ingestion-worker`:

1. orchestrator tick: due source scheduling + `sync.requested` consumption
2. connector tick: source fetch + LLM parse + `ingest_results` write
3. core apply tick: apply ingestion result into observation/proposal model

Execution order per tick is fixed:

1. `run_orchestrator_tick(db, worker_id)`
2. `run_connector_tick(db, worker_id)`
3. `run_core_apply_tick(db)`

Tick interval comes from `INGESTION_TICK_SECONDS` (default `2`).

### Layer 2: Review + DB + API

Owned by `app.main` and PostgreSQL:

1. V2 APIs for onboarding, user, input sources, sync, oauth/webhooks
2. review APIs for unified change pool (`/v2/review-items/changes`)
3. read APIs for canonical output (`/v2/change-events`, `/v2/timeline-events`)
4. health and UI routes

Canonical write policy:

1. ingestion apply creates pending proposals (`changes.review_status=pending`)
2. reviewer decision `approve` mutates canonical `events`
3. `reject` keeps canonical events unchanged

### Layer 3: Notification

Owned by `notification-worker`:

1. periodic digest processing via `process_due_digests(db)`
2. optional send based on `ENABLE_NOTIFICATIONS`

Tick interval comes from `NOTIFICATION_TICK_SECONDS` (default `30`).

## 3) Dataflow Contracts

Primary asynchronous flow:

1. API writes `sync_requests` + outbox `sync.requested`
2. ingestion orchestrator consumes outbox -> creates `ingest_jobs`
3. connector consumes jobs -> writes `ingest_results` + outbox `ingest.result.ready`
4. core apply consumes result-ready -> writes observations/proposals
5. reviewer approves/rejects via API
6. notification worker sends digest for queued notifications

Exactly-once effect is guaranteed by outbox/inbox dedupe + request idempotency log.

## 4) LLM Parsing Runtime

Ingestion parsers (`calendar_v2`, `gmail_v2`) use unified LLM gateway:

1. protocol: OpenAI-compatible `chat/completions`
2. config source: env only
   - `INGESTION_LLM_MODEL`
   - `INGESTION_LLM_BASE_URL`
   - `INGESTION_LLM_API_KEY`
3. format-error retry policy: max 4 attempts (initial + 3 retries)

Non-format errors keep existing retry/dead-letter semantics.

## 5) Operational Invariants

1. single API service is the only public backend endpoint
2. no dependency on `app.state` runtime object
3. no dependency on removed scheduler config `scheduler_tick_seconds`
4. worker loops are isolated by responsibility:
   - ingestion logic in `services/ingestion_runtime/worker.py`
   - notification logic in `services/notification/worker.py`

## 6) Migration and Compatibility Notes

1. this is a hard-cut runtime shape
2. no compatibility layer for legacy service entrypoints
3. historical change rows without proposal source metadata may not support strict `source_id` filtering

## 7) Related Docs

1. `docs/api_surface_current.md`
2. `docs/deploy_three_layer_runtime.md`
