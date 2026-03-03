# CalendarDIFF Architecture (Microservice Transition, Shared PostgreSQL)

## 1) Runtime Topology

Current target runtime is 5 service APIs + PostgreSQL + Redis:

1. `input-service` (`services.input_api.main:app`)
2. `ingest-service` (`services.ingest_api.main:app`)
3. `llm-service` (`services.llm_api.main:app`)
4. `review-service` (`services.review_api.main:app`)
5. `notification-service` (`services.notification_api.main:app`)
6. `postgres`
7. `redis`

Each service runs as an independent process and owns a bounded domain.

## 2) Service Responsibilities

### input-service

1. input source lifecycle APIs
2. oauth session/callback
3. webhook enqueue
4. sync request enqueue
5. onboarding + user profile entry APIs

Primary write ownership:

1. `input_sources`
2. `input_source_configs`
3. `input_source_secrets`
4. `input_source_cursors`
5. `sync_requests`

### ingest-service

1. orchestrator tick
2. connector fetch runtime tick (fetch-only + llm task enqueue)
3. dead-letter replay internal APIs

Primary write ownership:

1. `ingest_jobs`
2. `ingest_results`
3. ingest-related outbox/inbox rows

### llm-service

1. consumes Redis LLM parse queue
2. enforces global LLM limiter (target/hard RPS)
3. executes parser calls (`calendar_v2` / `gmail_v2`)
4. writes `ingest_results` + emits `ingest.result.ready`

Primary write ownership:

1. `ingest_results` (idempotent by `request_id`)
2. `ingest_jobs` runtime state for llm stage
3. ingest-related outbox events (`ingest.result.ready`)

### review-service

1. consumes `ingest.result.ready`
2. builds `source_event_observations` and pending `changes`
3. approve/reject decision APIs
4. canonical event projection (`events`)
5. read APIs: timeline/change/review

Primary write ownership:

1. `source_event_observations`
2. `inputs` (canonical)
3. `events`
4. `changes`
5. `snapshots` + `snapshot_events`
6. gmail audit tables (`email_*`)
7. `ingest_apply_log`

### notification-service

1. consumes `review.pending.created`
2. writes `notifications`
3. processes due digests and writes `digest_send_log`

Primary write ownership:

1. `notifications`
2. `digest_send_log`

## 3) Event Flow Contracts

1. `sync.requested` (input -> ingest)
2. `ingest.result.ready` (ingest -> review)
3. `review.pending.created` (review -> notification)
4. `review.decision.approved|rejected` (review audit events)

See `docs/event_contracts.md` for payload schemas.

## 4) Shared PostgreSQL Policy

1. service boundary is enforced by table ownership + event contracts
2. cross-service write via DB direct mutation is disallowed by policy
3. `integration_outbox` and `integration_inbox` are shared infra tables with namespace isolation (`event_type`, `consumer_name`)

See `docs/service_table_ownership.md` and `scripts/check_table_ownership.py`.

## 5) Canonical Data Rule

1. ingestion only creates pending proposals
2. `approve` mutates canonical `events`
3. `reject` keeps canonical state unchanged

## 6) LLM Runtime Placement

1. LLM parsing runtime runs in `llm-service`
2. parser code remains in shared module `app/modules/ingestion/llm_parsers/*`
3. queue backend is Redis stream + retry zset
4. gateway protocol remains OpenAI-compatible `chat/completions`

## 7) Operational Notes

1. service APIs are independent; no single BFF gateway in target topology
2. default exposure is `input-service + review-service` only
3. `ingest-service + llm-service + notification-service` are internal-only in default compose
4. internal APIs use service token auth, not `X-API-Key`
5. required internal headers:
   - `X-Service-Name`
   - `X-Service-Token`
6. replay APIs belong to ingest-service internal surface (`/internal/v2/ingest-jobs/*`)
7. each service exposes `GET /internal/v2/metrics` for minimal SLO checks
8. SLO runbook: `docs/ops_microservice_slo.md`
