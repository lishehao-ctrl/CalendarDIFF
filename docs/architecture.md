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
2. connector fetch runtime tick (Gmail incremental fetch, ICS RFC delta parse)
3. enqueue llm parse tasks only for changed records/components
3. dead-letter replay internal APIs

Primary write ownership:

1. `ingest_jobs`
2. `ingest_results`
3. ingest-related outbox/inbox rows

### llm-service

1. consumes Redis LLM parse queue
2. enforces global LLM limiter (target/hard RPS)
3. executes parser calls (`calendar_v2` / `gmail_v2`) for changed payloads
4. writes deterministic removed records for ICS delta removals
5. writes `ingest_results` + emits `ingest.result.ready`

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
See `docs/dataflow_input_to_notification.md` for a high-level end-to-end dataflow map.

## 4) Shared PostgreSQL Policy

1. service boundary is enforced by table ownership + event contracts
2. cross-service write via DB direct mutation is disallowed by policy
3. `integration_outbox` and `integration_inbox` are shared infra tables with namespace isolation (`event_type`, `consumer_name`)

See `docs/service_table_ownership.md` and `scripts/check_table_ownership.py`.

## 5) Canonical Data Rule

1. ingestion only creates pending proposals
2. `approve` mutates canonical `events`
3. `reject` keeps canonical state unchanged
4. manual correction (`/v2/review-items/changes/corrections`) mutates canonical `events` directly
5. manual correction auto-rejects conflicting pending changes for the same `event_uid`
6. manual correction writes `review.decision.approved` audit event with `decision_origin=manual_correction`

## 6) LLM Runtime Placement

1. LLM parsing runtime runs in `llm-service`
2. parser code remains in shared module `app/modules/ingestion/llm_parsers/*`
3. queue backend is Redis stream + retry zset
4. gateway protocol remains OpenAI-compatible `chat/completions`
5. ICS path is delta-first (`UID + RECURRENCE-ID` component key); cancelled components map to removal records
6. ICS canonical fields are deterministic from parser/source and persisted as `source_canonical`
7. LLM output is enrichment-only (`course_parse` + metadata), persisted under `enrichment`
8. `course_parse` is LLM-only with strict schema validation; parser failures enter existing retry/dead-letter flow
9. pending/review diff only evaluates canonical source fields, not enrichment drift
10. review-service maintains `event_entities` for strong/weak course naming (`course_best` + aliases) based on 5 parsed parts only (`dept/number/suffix/quarter/year2`)
11. Gmail-to-ICS linker v2 is conservative (same-day ±30min time-first + course/signal scoring) and persists normalized link state in:
   - `event_entity_links` (auto/manual accepted links)
   - `event_link_candidates` (review queue for score band / low anchor confidence)
   - `event_link_blocks` (permanent rejected pairs)
12. `0.65 <= score < 0.85` enters link-candidate review APIs (`/v2/review-items/link-candidates*`) and does not trigger `review.pending.created`
13. blocked source/entity pairs are never auto-linked and never re-enter pending candidate flow until unblocked

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
