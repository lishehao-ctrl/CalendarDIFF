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
3. executes parser calls (`calendar_parser` / `gmail_parser`) for changed payloads
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
5. read APIs: review-items

Primary write ownership:

1. `source_event_observations`
2. `inputs` (canonical)
3. `events`
4. `changes`
5. `snapshots` + `snapshot_events`
6. `ingest_apply_log`

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
4. manual correction (`/review/corrections`) mutates canonical `events` directly
5. manual correction auto-rejects conflicting pending changes for the same `event_uid`
6. manual correction writes `review.decision.approved` audit event with `decision_origin=manual_correction`

## 6) LLM Runtime Placement

1. LLM parsing runtime runs in `llm-service`
2. parser code remains in shared module `app/modules/ingestion/llm_parsers/*`
3. queue backend is Redis stream + retry zset
4. gateway protocol remains OpenAI-compatible `chat/completions`
5. ICS path is delta-first (`UID + RECURRENCE-ID` component key); cancelled components map to removal records
6. ICS canonical fields are deterministic from parser/source and persisted as `source_canonical`
7. LLM output is enrichment-only (`course_parse`, `event_parts`, `link_signals`), persisted under `enrichment`
8. `course_parse` is LLM-only with strict schema validation; parser failures enter existing retry/dead-letter flow
9. pending/review diff only evaluates canonical source fields, not enrichment drift
10. review-service maintains `event_entities` for strong/weak course naming (`course_best` + aliases) based on 5 parsed parts only (`dept/number/suffix/quarter/year2`)
11. Parser payload contract is hard-cut to `obs_v3` envelope:
   - calendar record payload: `source_canonical` + `enrichment(course_parse,event_parts,link_signals,payload_schema_version=obs_v3)`
   - gmail record payload: `message_id` + `source_canonical` + `enrichment(course_parse,event_parts,link_signals,payload_schema_version=obs_v3)`
12. Gmail-to-ICS linker is inventory-rule driven (no same-day window or score-band thresholds) and persists normalized link state in:
   - `event_entity_links` (auto/manual accepted links)
   - `event_link_candidates` (review queue for deterministic rule misses / low anchor confidence)
   - `event_link_blocks` (permanent rejected pairs)
   - `event_link_alerts` (medium-risk non-blocking queue for auto-link without canonical pending)
13. Auto-link rules are deterministic:
   - require `dept+number` and `event_parts.type`
   - enforce suffix exact-match when inventory for that `dept+number` has any suffix
   - enforce `event_parts.index` exact-match when inventory for same course+type has multiple indexes
14. blocked source/entity pairs are never auto-linked and never re-enter pending candidate flow until unblocked
15. `event_link_alerts` is auto-resolved when higher-priority governance takes over (`candidate_opened`, `canonical_pending_created`, `link_removed`, `link_relinked`)
16. review API provides queue aggregation and bulk moderation helpers:
   - `GET /review/summary` (pending counts for `changes`, `link-candidates`, `link-alerts`)
   - `POST /review/link-candidates/batch/decisions` (`approve`/`reject`, partial success)
   - `POST /review/link-alerts/batch/decisions` (`dismiss`/`mark_safe`, partial success)

## 7) Operational Notes

1. service APIs are independent; no single BFF gateway in target topology
2. default exposure is `input-service + review-service` only
3. `ingest-service + llm-service + notification-service` are internal-only in default compose
4. internal APIs use service token auth, not `X-API-Key`
5. required internal headers:
   - `X-Service-Name`
   - `X-Service-Token`
6. replay APIs belong to ingest-service internal surface (`/internal/ingest/jobs/*`)
7. each service exposes `GET /internal/metrics` for minimal SLO checks
8. SLO runbook: `docs/ops_microservice_slo.md`
9. worker lifecycle is unified under FastAPI lifespan + AnyIO task groups via shared runtime helper (`app/runtime/worker_loop.py`)
10. worker tick failures are non-fatal by policy: log and continue next round

## 8) Module Boundaries (Service Decomposition)

### core_ingest

1. `apply_service.py`: orchestration only (`get_ingest_apply_status`, `apply_ingest_result_idempotent`)
2. `apply_orchestrator.py`: `apply_records` + canonical input bootstrap + post-apply pending rebuild wiring
3. `calendar_apply.py`: calendar observation apply + component/external id resolution
4. `gmail_apply.py`: gmail observation apply + link/candidate/auto-link decision flow
5. `payload_extractors.py`: `source_canonical` / `enrichment` normalization
6. `canonical_coercion.py`: strict canonical datetime/text coercion
7. `entity_profile.py`: `event_entities` profile evolution
8. `linking_engine.py`: link candidate/link/block resolution primitives
9. `observation_store.py`: observation upsert/deactivate/hash/title-guard
10. `pending_rebuild.py`: pending change rebuild + `review.pending.created` emission + link-alert upsert hook
11. `serialization.py`: canonical diff serialization helpers
12. `time_utils.py`: UTC normalization

### review_changes

1. `change_listing_service.py`: list/query/summary shape assembly
2. `change_decision_service.py`: viewed/approve/reject state machine + canonical apply
3. `evidence_preview_service.py`: evidence path resolution and preview
4. `change_event_codec.py`: shared event payload parse/serialize/equivalence helpers
5. `manual_correction_service.py`: orchestration only (`preview_manual_correction`, `apply_manual_correction`)
6. `manual_correction_target.py`: target event resolution + user/canonical input loading
7. `manual_correction_snapshot.py`: base snapshot and pending change reads
8. `manual_correction_builder.py`: patch build + timezone/datetime normalization
9. `manual_correction_audit.py`: conflicting pending rejection + audit outbox write
10. `change_common.py`: cross-cutting lightweight helpers only

### review_links

1. `summary_service.py`: pending queue counters
2. `candidates_query_service.py`: candidates/blocks read side
3. `candidates_decision_service.py`: approve/reject and block deletion
4. `links_service.py`: links list/delete/relink
5. `alerts_service.py`: medium-risk alert list/decision/batch + auto-resolution helpers
6. `common.py`: shared note normalization, id dedupe, entity/observation preview, batch result builders

### llm_runtime

1. `__init__.py`: module entry exports only
2. `worker_tick.py`: worker tick orchestration + message lifecycle
3. `queue_consumer.py`: Redis stream/retry consume/ack composition
4. `queue_producer.py`: enqueue producer API used by ingestion
5. `parse_pipeline.py`: parse dispatch (`gmail`/`calendar`/`calendar_delta_v1`) + limiter wrapper
6. `transitions.py`: failure/success state transitions and persistence template

### input_control_plane routers

1. `router.py`: top-level router composition only
2. `sources_router.py`: source CRUD endpoints
3. `sync_requests_router.py`: sync create/status endpoints
4. `oauth_router.py`: oauth session create + callback public router
5. `webhooks_router.py`: webhook ingest endpoint
6. `router_common.py`: shared user/source ownership checks and common error mapping

### runtime_kernel

1. `app/modules/runtime_kernel/*` is the shared lifecycle/queue kernel consumed by both `ingestion` and `llm_runtime`
2. kernel hosts `JobContext` loading, retry delay/error truncation helpers, transition templates (`retry/dead-letter/success`), and idempotent `ingest_result + outbox` upsert
3. kernel also hosts Redis stream primitives (`consume/claim/ack/retry zset/metrics`), while `llm_runtime/queue.py` stays as a thin config wrapper (`stream_key/group/redis client`)
4. dependency rule: kernel must not import `app.modules.ingestion.*` or `app.modules.llm_runtime.*`

### db models bounded contexts

1. model package is split by bounded context under `app/db/models/`:
   - `shared.py` (`User`, `IntegrationOutbox`, `IntegrationInbox`, `OutboxStatus`)
   - `input.py` (`InputSource*`, `SyncRequest`, input-domain enums)
   - `ingestion.py` (`IngestJob*`, `IngestResult`, ingestion enums)
   - `review.py` (`Input/Event/Change/Link*`, `SourceEventObservation`, `IngestApplyLog`, review enums)
   - `notify.py` (`Notification*`, `DigestSendLog`)
2. `app/db/model_registry.py` is the only metadata bootstrap point for Alembic and table-ownership checks (`load_all_models()`)
3. hard-cut rule: `app.db.models` monolith module is removed; callers import from bounded context modules directly

### Intentional Legacy Strings

1. legacy API strings remain only in negative-path tests to assert hard-cut 404 behavior
2. `oauth2/v2` in Google OAuth URLs is third-party endpoint versioning, not CalendarDIFF API versioning
