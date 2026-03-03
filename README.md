# CalendarDIFF

CalendarDIFF runs as 5 services with shared PostgreSQL + Redis and event-driven domain boundaries.

Core flow:

1. ingest input sources (ICS/Gmail) and parse with LLM
2. build pending review proposals from observations
3. approve proposals into canonical events
4. enqueue and send digest notifications

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

2. Build frontend assets:

```bash
cd frontend
npm ci
npm run build
cd ..
```

3. Start PostgreSQL and apply schema:

```bash
docker compose up -d postgres
alembic upgrade head
```

4. Run service APIs:

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

Frontend multi-base routing (required when `input-service` and `review-service` are on different ports):

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

## Testing

```bash
source .venv/bin/activate
python -m pytest -q
cd frontend && npm run typecheck && npm run lint && npm run build
```

## Documentation

1. `docs/architecture.md`
2. `docs/deploy_three_layer_runtime.md`
3. `docs/api_surface_current.md`
4. `docs/ops_retention_replay_smoke.md`
5. `docs/service_table_ownership.md`
6. `docs/event_contracts.md`
7. `docs/ops_microservice_slo.md`
