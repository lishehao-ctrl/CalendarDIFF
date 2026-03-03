# CalendarDIFF

CalendarDIFF runs as 5 services with shared PostgreSQL + Redis and event-driven domain boundaries.

Core flow:

1. ingest input sources (ICS/Gmail) and build event observations
2. ICS uses RFC-based delta detection first; only changed VEVENT components go to LLM
3. removed/cancelled ICS components are handled as deterministic removals
4. ICS canonical fields (`title/start/end/status/location`) stay deterministic from parser/source
5. LLM outputs enrichment only (`course_parse`, tags/type/confidence), not canonical identity fields
6. `course_parse` is LLM-only (no local regex/raw text fallback in review/apply)
7. strong/weak naming uses 5 parsed parts (`dept/number/suffix/quarter/year2`) with monotonic best-name updates
8. cross-source linker v2 persists normalized links/candidates/blocks and keeps candidate review out of pending-notification chain
9. link-candidate APIs: `GET /v2/review-items/link-candidates`, `POST /v2/review-items/link-candidates/{id}/decisions`, `GET/DELETE /v2/review-items/link-candidates/blocks*`
10. build pending review proposals from source canonical observations
11. approve proposals into canonical events
12. enqueue and send digest notifications
13. allow manual due correction when parsed result is wrong

## Runtime Topology (5 Services + PostgreSQL + Redis)

1. `input-service` (`services.input_api.main:app`)
2. `ingest-service` (`services.ingest_api.main:app`)
3. `llm-service` (`services.llm_api.main:app`)
4. `review-service` (`services.review_api.main:app`)
5. `notification-service` (`services.notification_api.main:app`)
6. `postgres`
7. `redis`

## Quick Start

1. Create environment and install dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

2. Start PostgreSQL and apply schema:

```bash
docker compose up -d postgres
alembic upgrade head
```

### Migration Revision Rename Note

This cleanup rewrites migration revision identifiers in `app/db/migrations/versions`.
If an environment still tracks older revision IDs, use one of the following:

1. reset and re-init (preferred for local/dev):

```bash
scripts/reset_postgres_db.sh
alembic upgrade head
```

2. controlled revision remap (existing DB state is kept):

```sql
-- run on the target database
UPDATE alembic_version
SET version_num = '20260302_0004_src_bridge_map'
WHERE version_num LIKE '20260302_0004_src_%_map'
  AND version_num <> '20260302_0004_src_bridge_map';
```

Then run:

```bash
alembic upgrade head
```

3. Run service APIs:

```bash
SERVICE_NAME=input RUN_MIGRATIONS=false PORT=8001 ./scripts/start_service.sh
SERVICE_NAME=ingest RUN_MIGRATIONS=false PORT=8002 ./scripts/start_service.sh
SERVICE_NAME=llm RUN_MIGRATIONS=false PORT=8005 ./scripts/start_service.sh
SERVICE_NAME=review RUN_MIGRATIONS=false PORT=8000 ./scripts/start_service.sh
SERVICE_NAME=notification RUN_MIGRATIONS=false PORT=8004 ./scripts/start_service.sh
```

## Docker Compose

Run full local stack:

```bash
docker compose up --build
```

Compose includes:

1. `postgres`
2. `redis`
3. `input-service`
4. `ingest-service`
5. `llm-service`
6. `review-service`
7. `notification-service`

Default host-exposed ports:

1. `input-service` on `localhost:8001`
2. `review-service` on `localhost:8000`

`ingest-service`, `llm-service`, and `notification-service` are internal-only in default compose. Use `docker-compose.dev.yml` for dev-only port exposure.

## Core Environment Variables

Required:

```env
APP_API_KEY=dev-api-key-change-me
APP_SECRET_KEY=7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk=
INTERNAL_SERVICE_TOKEN_INPUT=dev-internal-token-input
INTERNAL_SERVICE_TOKEN_INGEST=dev-internal-token-ingest
INTERNAL_SERVICE_TOKEN_REVIEW=dev-internal-token-review
INTERNAL_SERVICE_TOKEN_NOTIFICATION=dev-internal-token-notification
INTERNAL_SERVICE_TOKEN_LLM=dev-internal-token-llm
INTERNAL_SERVICE_TOKEN_OPS=dev-internal-token-ops
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff
REDIS_URL=redis://localhost:6379/0
PUBLIC_WEB_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
```

Ingestion LLM (chat/completions only):

```env
INGESTION_LLM_MODEL=gpt-5.3-codex
INGESTION_LLM_BASE_URL=
INGESTION_LLM_API_KEY=
```

Optional Gmail endpoint overrides (for local fake-provider smoke only):

```env
GMAIL_API_BASE_URL=http://127.0.0.1:8765/gmail/v1/users/me
GMAIL_OAUTH_TOKEN_URL=http://127.0.0.1:8765/oauth2/token
GMAIL_OAUTH_AUTHORIZE_URL=http://127.0.0.1:8765/oauth2/auth
```

Worker intervals (embedded in service processes):

```env
INGESTION_TICK_SECONDS=2
LLM_SERVICE_ENABLE_WORKER=true
REVIEW_APPLY_TICK_SECONDS=2
NOTIFICATION_TICK_SECONDS=30
```

Optional per-service base URLs (useful when services run on different ports):

```env
INPUT_API_BASE_URL=http://localhost:8001
REVIEW_API_BASE_URL=http://localhost:8000
INGEST_API_BASE_URL=http://localhost:8002
NOTIFY_API_BASE_URL=http://localhost:8004
```

## Internal Ops Auth

`/internal/v2/*` endpoints no longer accept `X-API-Key`.

Use service token headers:

```http
X-Service-Name: ops
X-Service-Token: <INTERNAL_SERVICE_TOKEN_OPS>
```

Worker toggles:

```env
INGEST_SERVICE_ENABLE_WORKER=true
REVIEW_SERVICE_ENABLE_APPLY_WORKER=true
NOTIFICATION_SERVICE_ENABLE_WORKER=true
ENABLE_NOTIFICATIONS=false
```

## Health Checks

```bash
curl -s http://localhost:8001/health
curl -s http://localhost:8002/health
curl -s http://localhost:8005/health
curl -s http://localhost:8000/health
curl -s http://localhost:8004/health
```

## Real Source Smoke (3 Rounds)

```bash
python scripts/smoke_real_sources_three_rounds.py \
  --input-api-base http://127.0.0.1:8001 \
  --review-api-base http://127.0.0.1:8000 \
  --report data/synthetic/v2_ddlchange_160/qa/real_source_smoke_report.json
```

Full closure check:

```bash
python scripts/smoke_microservice_closure.py \
  --input-api-base http://127.0.0.1:8001 \
  --review-api-base http://127.0.0.1:8000 \
  --ingest-api-base http://127.0.0.1:8002 \
  --notify-api-base http://127.0.0.1:8004 \
  --llm-api-base http://127.0.0.1:8005
```

SLO check:

```bash
python scripts/ops_slo_check.py \
  --input-base http://127.0.0.1:8001 \
  --ingest-base http://127.0.0.1:8002 \
  --review-base http://127.0.0.1:8000 \
  --notify-base http://127.0.0.1:8004 \
  --llm-base http://127.0.0.1:8005 \
  --ops-token "${INTERNAL_SERVICE_TOKEN_OPS}" \
  --json
```

OpenAPI snapshots:

```bash
python scripts/update_openapi_snapshots.py
```

## API Surface

Detailed snapshot:

1. `docs/api_surface_current.md`
2. `docs/event_contracts.md`

## Manual Due Correction

When the parser extracts an incorrect due time, review-service supports direct canonical correction APIs:

1. `POST /v2/review-items/changes/corrections/preview`
2. `POST /v2/review-items/changes/corrections`

Behavior:

1. target can be provided by `change_id` or `event_uid`
2. `patch.due_at` accepts date-only, local datetime, or timezone-aware datetime
3. date-only is normalized to `23:59` in `users.timezone_name` then converted to UTC
4. conflicting pending changes for the same `event_uid` are auto-rejected
5. correction writes an approved audit change and emits `review.decision.approved` with `decision_origin=manual_correction`

## Canonical vs Enrichment (MVP)

1. ICS canonical diff is source-deterministic; LLM does not rewrite canonical title/time.
2. Gmail/ICS `course_parse` is strictly LLM-derived with schema validation; invalid payloads fail parse and enter retry/dead-letter flow.
3. Cross-source linking is time-anchor first and conservative; when Gmail parse lacks reliable `dept+number`, auto-link is disabled (candidate metadata only).
4. Strong/weak naming uses only the 5 parsed parts (`dept/number/suffix/quarter/year2`) and updates `course_best` monotonically.
5. Pending generation reacts to canonical change only; enrichment-only drift does not trigger notification flow.

## Testing

```bash
source .venv/bin/activate
python -m pytest -q
```

## Documentation

1. `docs/architecture.md`
2. `docs/deploy_three_layer_runtime.md`
3. `docs/api_surface_current.md`
4. `docs/ops_retention_replay_smoke.md`
5. `docs/service_table_ownership.md`
6. `docs/event_contracts.md`
7. `docs/ops_microservice_slo.md`
8. `docs/dataflow_input_to_notification.md`
