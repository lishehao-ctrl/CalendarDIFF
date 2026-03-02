# CalendarDIFF Architecture (Input Microservices Cutover)

## 1) Runtime Topology

Input domain is split into independently deployable services (same repo, multiple entrypoints):

1. `input-control-plane-api` (`services/input_control_plane/main.py`)
2. `ingestion-orchestrator-worker` (`services/ingestion_orchestrator/worker.py`)
3. `connector-runtime-worker` (`services/connector_runtime/worker.py`)
4. `core-api` (`services/core_api/main.py`)
5. `core-apply-worker` (`services/core_apply_worker/worker.py`)

Short-term deployment keeps a shared PostgreSQL database for all services.

## 2) Service Boundaries

### Input Control Plane API

Owns:

1. input source lifecycle (`input_sources`)
2. source config/secrets/cursor management
3. sync request creation and webhook ingestion
4. oauth bootstrap/callback for connector credentials

Does not own:

1. scheduler loop execution
2. provider fetch/parse runtime
3. core-domain business apply

### Ingestion Orchestrator Worker

Owns:

1. poll scheduling (`next_poll_at`)
2. outbox event consumption for `sync.requested`
3. ingest job creation and queue state transitions
4. inbox dedupe for orchestrator consumer

Does not own:

1. provider API calls
2. user-facing APIs

### Connector Runtime Worker

Owns:

1. ingest job claiming (`FOR UPDATE SKIP LOCKED`)
2. provider connector execution
3. ingest result persistence (`ingest_results`)
4. result event emission (`ingest.result.ready`)
5. retry/dead-letter transitions

Does not own:

1. user-facing APIs
2. core-domain apply logic

### Core API + Apply Worker

Owns:

1. existing core read/review surfaces (`changes`, `events`, `review`)
2. internal idempotent apply API:
   - `POST /internal/v2/ingest-results/applications`
   - `GET /internal/v2/ingest-results/{request_id}`
3. apply-consumer worker consuming `ingest.result.ready`

Does not own:

1. input source provisioning
2. oauth/webhook entry

## 3) Contracts and States

### Source kind

`calendar | email | task | exam | announcement`

### Trigger type

`manual | scheduler | webhook`

### Connector result status

`NO_CHANGE | CHANGED | FETCH_FAILED | PARSE_FAILED | AUTH_FAILED | RATE_LIMITED`

### Exactly-once effect design

1. control plane writes `sync_requests` + `integration_outbox(sync.requested)` in one transaction
2. orchestrator consumes with `integration_inbox` dedupe and creates unique `ingest_jobs(request_id)`
3. connector writes unique `ingest_results(request_id)` + outbox `ingest.result.ready`
4. core apply inserts unique `ingest_apply_log(request_id)` before applying effect
5. retries may duplicate delivery attempts but cannot duplicate business effect

## 4) Input APIs (Breaking v2)

External:

1. `POST /v2/input-sources`
2. `GET /v2/input-sources`
3. `PATCH /v2/input-sources/{source_id}`
4. `DELETE /v2/input-sources/{source_id}`
5. `POST /v2/sync-requests`
6. `GET /v2/sync-requests/{request_id}`
7. `POST /v2/oauth-sessions`
8. `GET /v2/oauth-callbacks/{provider}`
9. `POST /v2/webhook-events/{source_id}/{provider}`

Internal ops:

1. `POST /internal/v2/ingest-jobs/{job_id}/replays`
2. `POST /internal/v2/ingest-jobs/dead-letter/replays`

Core internal:

1. `POST /internal/v2/ingest-results/applications` (`Idempotency-Key == request_id`)
2. `GET /internal/v2/ingest-results/{request_id}`

## 5) Onboarding Semantics (Updated)

Onboarding stage is now:

1. `needs_user`
2. `needs_source_connection`
3. `ready`

`ready` means the user has at least one active `input_source`; it no longer depends on a single ICS baseline path.

## 6) LLM Gateway Status

Calendar and Gmail ingestion parsers run through a unified `LLM Gateway`:

1. gateway is OpenAI-compatible `chat/completions` mode only
2. runtime config comes from env only:
   - `INGESTION_LLM_MODEL`
   - `INGESTION_LLM_BASE_URL`
   - `INGESTION_LLM_API_KEY`
3. connector runtime routes `calendar` and `gmail` through `app/modules/ingestion/llm_parsers/*`, which call `app/modules/llm_gateway/*`
4. legacy parser code remains archived under `app/modules/sync/archive/*`
5. Gmail connector flow is:
   - read cursor `history_id`
   - `list_history(start_history_id)` for incrementals
   - fetch message metadata/body
   - call gmail LLM parser per message
6. Calendar connector flow is:
   - fetch ICS with etag/last-modified
   - decode + truncate payload
   - call calendar LLM parser
7. parser failures map to `PARSE_FAILED` with explicit error codes:
   - `parse_llm_calendar_schema_invalid`
   - `parse_llm_gmail_schema_invalid`
   - `parse_llm_calendar_upstream_error`
   - `parse_llm_gmail_upstream_error`
   - `parse_llm_timeout`
   - `parse_llm_empty_output`
