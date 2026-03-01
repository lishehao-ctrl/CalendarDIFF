# Input Microservices Cutover Notes (V2 Hard-Cut Completed)

## Scope

Input-domain runtime is split into:

1. `input-control-plane-api`
2. `ingestion-orchestrator-worker`
3. `connector-runtime-worker`
4. `core-api`
5. `core-apply-worker`
6. `gateway` (single public ingress)

Current phase keeps shared PostgreSQL.

## Deploy

Use Docker Compose multi-service topology:

```bash
docker compose up --build
```

Default ingress:

1. Gateway: `:8000`
2. Health: `GET /health` (not versioned)

## Breaking Changes (Applied)

1. External input surface moved to `/v2/input-sources/*`.
2. Sync trigger changed to resource API:
   - `POST /v2/sync-requests`
   - `GET /v2/sync-requests/{request_id}`
3. Internal ingest endpoints moved to `/internal/v2/*`.
4. Onboarding stage is `needs_user | needs_source_connection | ready`.

## Exactly-once Effect Guarantees

Implemented with:

1. `integration_outbox` for event publication
2. `integration_inbox` for consumer dedupe
3. unique constraints on `sync_requests`, `ingest_jobs`, `ingest_results`, `ingest_apply_log`
4. idempotency validation on `POST /internal/v2/ingest-results/applications`

## Operational Replay

Dead-letter replay endpoints:

1. `POST /internal/v2/ingest-jobs/{job_id}/replays`
2. `POST /internal/v2/ingest-jobs/dead-letter/replays?limit=100`

## Gateway Routing

`gateway` forwards:

1. `/v2/input-sources*`, `/v2/sync-requests*`, `/v2/oauth-*`, `/v2/webhook-events*`, `/v2/users*`, `/v2/onboarding*`, `/internal/v2/ingest-jobs*` -> input control plane
2. `/v2/change-events*`, `/v2/timeline-events*`, `/v2/review-items*`, `/internal/v2/ingest-results*`, `/ui*`, `/health` -> core api
