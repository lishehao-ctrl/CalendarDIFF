# CalendarDIFF Architecture (Modular Monolith Runtime)

## 1) Runtime Topology

Current default runtime is a modular monolith backend + frontend + PostgreSQL + Redis:

1. `backend-service` (`services.app_api.main:app`)
2. `frontend`
3. `postgres`
4. `redis`

The backend-service is the only default API process. Domain boundaries are preserved at the module/service layer, not the HTTP process layer.

## 2) Module Responsibilities

### sources / onboarding / auth

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

### ingest / llm / runtime

1. orchestrator tick
2. connector fetch runtime tick (Gmail incremental fetch, ICS RFC delta parse)
3. enqueue llm parse tasks only for changed records/components
4. consume parse queue and persist ingest results

Primary write ownership:

1. `ingest_jobs`
2. `ingest_results`
3. ingest-related outbox/inbox rows

### review / links / edits

1. consumes `ingest.result.ready`
2. builds `source_event_observations` and pending `changes` for resolvable records only
3. approve/reject decision APIs
4. approved semantic projection (`event_entities`)
5. read APIs: review-items

Primary write ownership:

1. `source_event_observations`
2. `event_entities`
3. `changes`
4. `ingest_apply_log`
5. `ingest_unresolved_records` (ingest-side unresolved isolation bucket)

### notification

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
   - `family_id` is the only label authority
   - user-facing display resolves latest `course_work_item_label_families.canonical_label` by `family_id`
   - `event_entities` no longer persists `family_name`; display label is read-time projection only
   - `changes.family_name` may remain as frozen audit payload, not default display authority
   - missing `family_id` or missing family-row label authority is a data-integrity error (not a normal `"Unknown"` UI branch)
8. family lifecycle hardening:
   - family rows are not a normal hard-delete target
   - `DELETE /users/me/course-work-item-families/{family_id}` is intentionally removed; update/relink flows remain the product path
9. family rebuild path is observation-native:
   - `course_work_item_family_rebuild` recomputes from active runtime observations directly
   - it does not replay parser-stage payloads or call pseudo-ingest apply
10. unresolved ingest isolation:
   - missing course identity routes records to `ingest_unresolved_records`
   - unresolved records do not upsert normal `source_event_observations`
   - unresolved records do not create pending `changes` and do not emit `review.pending.created`
   - later resolvable ingests for the same source/external record mark unresolved rows as resolved/superseded
11. source term window is explicit and user-provided for active Gmail/ICS sources:
   - `InputSource` is the provider/auth handle; `config.term_key + term_from + term_to` define the active source-term binding
   - raw Gmail/ICS fetch cache may be shared over time, but runtime observations/pending proposals only stay in scope through the active source-term binding
   - `config.term_key`, `config.term_from`, and `config.term_to` are the only term-boundary inputs
   - backend derives fixed runtime bounds: `bootstrap_from = term_from - 30d`, `monitor_from = term_from`, `monitor_until = term_to + 30d`, `archive_after = monitor_until`
   - scheduler/manual sync treats `monitor_from` as start and `archive_after` as archive cutoff
   - content outside `[bootstrap_from, monitor_until]` does not enter the normal observation/change flow
   - changing term config is a source-scoped rescope operation, not a plain config edit:
     - source observations, unresolved rows, source link state, and source cursor are cleared/reset
     - affected pending proposals are rebuilt against remaining in-scope observations
     - if the new term has already started and is not expired, a fresh `term_rescope` sync request is enqueued automatically
   - if term config is edited while source sync is `QUEUED`/`RUNNING`, backend stores a single coalesced `config.pending_term_rebind` and applies it on the first terminal status (`SUCCEEDED`/`FAILED`)
12. source runtime state is an explicit backend projection:
   - `lifecycle_state`: `active | inactive | archived`
   - `sync_state`: `idle | queued | running`
   - `config_state`: `stable | rebind_pending`
   - API may expose a summarized `runtime_state`, but the projection remains the source of truth
13. manual canonical edits create sticky strongest support on `event_entities`:
   - canonical edit sets `event_entities.manual_support = true`
   - source rescope/churn may remove source-scoped observations and links, but it must not auto-produce `removed` proposals for entities with manual support and no remaining automatic observations
   - remaining automatic observations may still generate normal pending changes against the manually approved entity state

## 6) LLM Runtime Placement

1. LLM parsing runtime runs in `llm-service`
2. parser code remains in shared module `app/modules/ingestion/llm_parsers/*`
3. queue backend is Redis stream + retry zset
4. gateway protocol path follows `INGESTION_LLM_API_MODE` and supports both OpenAI-compatible `/responses` and `/chat/completions`
5. ICS path is delta-first (`UID + RECURRENCE-ID` component key); cancelled components map to removal records
6. ICS source facts are deterministic from parser/source and persisted as `source_facts`
7. parser output is parser-stage only and source-specific:
   - gmail parser payload: `message_id` + `source_facts` + `semantic_event_draft` + `link_signals`
   - calendar parser payload: `source_facts` + `semantic_event_draft`
8. apply/runtime normalizes parser-stage payloads into observation runtime envelope:
   - `source_facts`
   - `semantic_event`
   - `kind_resolution`
   - optional `link_signals` for sources that actually provide them (gmail)
9. `semantic_event` is the only active runtime semantic field; `semantic_event_draft` is parser-stage only
10. `enrichment` is not an active runtime observation contract
11. pending/review diff evaluates normalized semantic fields from runtime `semantic_event`
12. review-service maintains `event_entities` for strong/weak course naming (`course_best` + aliases) based on 5 parsed parts only (`dept/number/suffix/quarter/year2`)
13. source-aware parser routing is centralized:
   - shared `source_orchestrator` decides provider route before source-specific parsing
   - gmail path uses sender-family aware routing
   - calendar path uses deterministic `VEVENT` normalization plus two-pass classification
14. gmail parser workflow is two-pass in backend runtime:
   - pass 1 planner emits `message_id + mode + segment_array` (`segment_type_hint`: `atomic|directive|unknown`)
   - pass 2 extracts `atomic` segments into `gmail.message.extracted` and `directive` segments into `gmail.directive.extracted`
   - directive records do not create fake observations; they apply deterministically into normal pending `changes`
15. calendar parser workflow is two-pass in backend runtime:
   - pass 1 classifies each `VEVENT` as `relevant|unknown`
   - pass 2 runs only for relevant items and extracts minimal semantic classification (`course identity + raw_type + event_name + ordinal + confidence + evidence`)
   - calendar time fields are derived deterministically from `DTSTART/DTEND/DUE`, not by LLM
   - calendar runtime path does not depend on LLM-produced `link_signals`
16. term window gating is source-term-binding-wide and provider-specific:
   - Gmail bootstrap/history fetch uses `[bootstrap_from, monitor_until]` as coarse message-time gate
   - ICS delta keeps only changed `VEVENT`s whose deterministic event date falls inside `[bootstrap_from, monitor_until]`
   - apply/runtime performs a second term gate and isolates out-of-scope records into `ingest_unresolved_records`
   - source patch/update that changes term window performs immediate rescope when no in-flight sync exists; otherwise it queues one pending rebind and applies after terminal sync completion
17. Gmail-to-ICS linker is inventory-rule driven (no same-day window or score-band thresholds) and persists normalized link state in:
   - `event_entity_links` (auto/manual accepted links)
   - `event_link_candidates` (review queue for deterministic rule misses / low anchor confidence)
   - `event_link_blocks` (permanent rejected pairs)
18. Auto-link rules are deterministic:
   - require `dept+number` and `semantic_event.raw_type`
   - enforce suffix exact-match when inventory for that `dept+number` has any suffix
   - enforce `semantic_event.ordinal` exact-match when inventory for same course+raw_type has multiple ordinals
19. blocked source/entity pairs are never auto-linked and never re-enter pending candidate flow until unblocked
20. review API provides queue aggregation and bulk moderation helpers:
   - `GET /review/summary` (pending counts for `changes`, `link-candidates`)
   - `POST /review/link-candidates/batch/decisions` (`approve`/`reject`, partial success)

## 7) Operational Notes

1. default local and compose runtime starts one backend API process
2. background workers run inside that same backend process under FastAPI lifespan
3. PostgreSQL and Redis remain shared infrastructure dependencies
4. worker lifecycle stays unified under FastAPI lifespan + AnyIO task groups via shared runtime helper
5. worker tick failures remain non-fatal by policy: log and continue next round
6. legacy split-service entrypoints remain only as migration/debug artifacts and are not the default runtime path

## 8) Module Boundaries (Service Decomposition)

### core_ingest

1. `apply.py`: ingest apply status, semantic apply orchestration, and idempotent result application
3. `calendar_apply.py`: calendar observation apply + component/external id resolution
4. `gmail_apply.py`: gmail observation apply + link/candidate/auto-link decision flow
5. `payload_extractors.py`: parser-stage extraction + runtime semantic normalization (`semantic_event_draft` -> `semantic_event`)
6. `source_facts_coercion.py`: strict source-facts datetime/text coercion
7. `source_identity.py`: `entity_uid`-first source-scoped identity construction
8. `linking_engine.py`: link candidate/link/block resolution primitives
9. `observation_store.py`: observation upsert/deactivate/hash/title-guard
10. `pending_proposal_rebuild.py`: pending proposal decision planner + rebuild orchestration
11. `pending_change_store.py`: pending change upsert/reject templates
12. `pending_review_outbox.py`: `review.pending.created` outbox emission
13. `time_utils.py`: UTC normalization

### review_changes

1. `change_listing_service.py`: review list/get response assembly over the batched projection
2. `change_decision_service.py`: viewed/approve/reject state machine + approved entity apply
3. `evidence_preview_service.py`: frozen change evidence preview
4. `edit_service.py`: review edit entrypoint for proposal/canonical flows
5. `canonical_edit_preview_flow.py`: preview response assembly and idempotent preview checks
6. `canonical_edit_apply_txn.py`: canonical edit apply transaction body (lock/update/change/audit)
7. `canonical_edit_target.py`: target entity resolution + user loading
8. `canonical_edit_snapshot.py`: approved semantic payload and pending change reads
9. `canonical_edit_builder.py`: semantic patch build + due-field validation
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
5. `summary_service.py`: pending queue counters
6. `candidates_query_service.py`: candidates/blocks read side
7. `candidates_decision_service.py`: approve/reject and block deletion
8. `links_service.py`: links list/delete/relink
9. `common.py`: shared note normalization, id dedupe, entity/observation preview, batch result builders

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
