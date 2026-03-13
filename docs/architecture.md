# CalendarDIFF Architecture (Shared PostgreSQL Runtime)

## 1) Runtime Topology

Current target runtime is a unified public gateway + 5 service APIs + PostgreSQL + Redis:

1. `public-service` (`services.public_api.main:app`)
2. `input-service` (`services.input_api.main:app`, internal metrics/runtime only)
3. `ingest-service` (`services.ingest_api.main:app`)
4. `llm-service` (`services.llm_api.main:app`)
5. `review-service` (`services.review_api.main:app`, internal apply/runtime only)
6. `notification-service` (`services.notification_api.main:app`)
7. `postgres`
8. `redis`

The public-service is the only user-facing gateway. Internal services continue to run as independent processes and own bounded domains.

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
4. approved semantic projection (`event_entities`)
5. read APIs: review-items

Primary write ownership:

1. `source_event_observations`
2. `event_entities`
3. `changes`
4. `ingest_apply_log`

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
2. `approve` mutates approved semantic state in `event_entities`
3. `reject` keeps approved entity state unchanged
4. unified edits (`/review/edits`) support both proposal edits and direct approved-entity edits (`mode=canonical` route name remains stable)
5. canonical edit mode auto-rejects conflicting pending changes for the same `entity_uid`
6. canonical edit mode continues to write `review.decision.approved` audit events with `decision_origin=canonical_edit`
7. family label authority is explicit:
   - `event_entities.family_id` is the stable authority
   - `event_entities.family_name` is an approved snapshot only
   - current approved-entity display resolves latest `course_work_item_label_families.canonical_label` by `family_id`
   - `changes.family_name` stays frozen at detection/edit time
   - review notifications and review history display the frozen `changes.family_name`, not the latest renamed label

## 6) LLM Runtime Placement

1. LLM parsing runtime runs in `llm-service`
2. parser code remains in shared module `app/modules/ingestion/llm_parsers/*`
3. queue backend is Redis stream + retry zset
4. gateway protocol remains OpenAI-compatible `chat/completions`
5. ICS path is delta-first (`UID + RECURRENCE-ID` component key); cancelled components map to removal records
6. ICS source facts are deterministic from parser/source and persisted as `source_facts`
7. LLM output is enrichment-only (`course_parse`, `event_parts`, `link_signals`), persisted under `enrichment`
8. `course_parse` is LLM-only with strict schema validation; parser failures enter existing retry/dead-letter flow
9. pending/review diff only evaluates semantic source fields, not enrichment drift
10. review-service maintains `event_entities` for strong/weak course naming (`course_best` + aliases) based on 5 parsed parts only (`dept/number/suffix/quarter/year2`)
11. Parser payload contract is fixed at `obs_v3` envelope:
   - calendar record payload: `source_facts` + `enrichment(course_parse,event_parts,link_signals,payload_schema_version=obs_v3)`
   - gmail record payload: `message_id` + `source_facts` + `enrichment(course_parse,event_parts,link_signals,payload_schema_version=obs_v3)`
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

1. `apply.py`: ingest apply status, semantic apply orchestration, and idempotent result application
3. `calendar_apply.py`: calendar observation apply + component/external id resolution
4. `gmail_apply.py`: gmail observation apply + link/candidate/auto-link decision flow
5. `payload_extractors.py`: `source_facts` / `enrichment` normalization
6. `source_facts_coercion.py`: strict source-facts datetime/text coercion
7. `source_identity.py`: `entity_uid`-first source-scoped identity construction
8. `linking_engine.py`: link candidate/link/block resolution primitives
9. `observation_store.py`: observation upsert/deactivate/hash/title-guard
10. `pending_proposal_rebuild.py`: pending proposal decision planner + rebuild orchestration
11. `pending_change_store.py`: pending change upsert/reject templates
12. `pending_review_outbox.py`: `review.pending.created` outbox emission
13. `pending_auto_link_alerts.py`: auto-link alert emit for non-pending entities
14. `time_utils.py`: UTC normalization

### review_changes

1. `change_listing_service.py`: review list/get response assembly over the batched projection
2. `change_decision_service.py`: viewed/approve/reject state machine + approved entity apply
3. `evidence_preview_service.py`: frozen change evidence preview
4. `edit_service.py`: review edit entrypoint for proposal/canonical flows
5. `canonical_edit_preview_flow.py`: preview response assembly and idempotent preview checks
6. `canonical_edit_apply_txn.py`: canonical edit apply transaction body (lock/update/change/audit)
7. `canonical_edit_target.py`: target entity resolution + user loading
8. `canonical_edit_snapshot.py`: approved semantic payload and pending change reads
9. `canonical_edit_builder.py`: patch build + timezone/datetime normalization
10. `canonical_edit_audit.py`: conflicting pending rejection + audit outbox write
11. `review_projection.py`: batched source/observation projection for review list and summary display

### common

1. `course_identity.py`: normalized course identity parsing/display
2. `event_display.py`: strict user-facing event display projection
3. `family_labels.py`: family label authority resolution and equivalence rules
4. `payload_schemas.py`: typed schemas for approved semantic payloads, source facts, frozen evidence, source refs, and review summaries
5. `semantic_codec.py`: shared approved-entity semantic parse/serialize/equivalence primitives

### review_links

1. `router.py`: top-level router composition only
2. `summary_router.py`: `/review/summary` endpoint
3. `candidates_router.py`: `/review/link-candidates/*` endpoints
4. `links_router.py`: `/review/links/*` endpoints
5. `alerts_router.py`: `/review/link-alerts/*` endpoints
6. `summary_service.py`: pending queue counters
7. `candidates_query_service.py`: candidates/blocks read side
8. `candidates_decision_service.py`: approve/reject and block deletion
9. `links_service.py`: links list/delete/relink
10. `alerts_upsert_service.py`: alert upsert and auto-resolution helpers
11. `alerts_query_service.py`: alerts read model assembly
12. `alerts_decision_service.py`: dismiss/mark-safe and batch decisions
13. `alerts_errors.py`: alert domain exceptions
14. `common.py`: shared note normalization, id dedupe, entity/observation preview, batch result builders

### llm_runtime

1. `__init__.py`: module entry exports only
2. `tick_runner.py`: worker tick orchestration + concurrent message fan-out + ack aggregation
3. `message_preflight.py`: DB lock/context validation + `LLM_RUNNING` stage transition
4. `message_processor.py`: single-message lifecycle (`preflight -> parse -> transition`)
5. `parse_pipeline.py`: parse dispatch (`gmail`/`calendar`/`calendar_delta`) + limiter wrapper
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
3. kernel also hosts parse-task queue port and Redis stream primitives (`consume/claim/ack/retry zset/metrics`) via `parse_task_queue.py` and `stream_queue.py`
4. dependency rule: kernel must not import `app.modules.ingestion.*` or `app.modules.llm_runtime.*`

### db models bounded contexts

1. model package is split by bounded context under `app/db/models/`:
   - `shared.py` (`User`, `IntegrationOutbox`, `IntegrationInbox`, `OutboxStatus`)
   - `input.py` (`InputSource*`, `SyncRequest`, input-domain enums)
   - `ingestion.py` (`IngestJob*`, `IngestResult`, ingestion enums)
   - `review.py` (`EventEntity`, `Change`, link review tables, `SourceEventObservation`, `IngestApplyLog`, review enums)
   - `notify.py` (`Notification*`, `DigestSendLog`)
2. `app/db/model_registry.py` is the only metadata bootstrap point for Alembic and table-ownership checks (`load_all_models()`)
3. rule: `app.db.models` monolith module is removed; callers import from bounded context modules directly
