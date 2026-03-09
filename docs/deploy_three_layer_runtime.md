# Deploy Microservice Runtime (Shared PostgreSQL)

## Goal

Run backend as a public gateway plus 5 internal services, PostgreSQL, and Redis:

1. public-service
2. input-service
3. ingest-service
4. llm-service
5. review-service
6. notification-service
7. postgres
8. redis

## Current Runtime Notes

1. local launcher flow uses `3000 / 8200 / 8201 / 8202 / 8203 / 8204 / 8205`
2. compose host exposure remains a separate compatibility path and may expose different host ports
3. public dashboard traffic is session-based and enters through the frontend, not by anonymously calling backend APIs
4. input-service owns source lifecycle, OAuth session/callback, onboarding, and user profile APIs

## Prerequisites

1. `.env` configured with DB and app secrets
2. PostgreSQL reachable from all services
3. schema migrated to head (`alembic upgrade head`)

## Core Environment

Required:

```env
APP_API_KEY=...
APP_SECRET_KEY=...
INTERNAL_SERVICE_TOKEN_INPUT=...
INTERNAL_SERVICE_TOKEN_INGEST=...
INTERNAL_SERVICE_TOKEN_REVIEW=...
INTERNAL_SERVICE_TOKEN_NOTIFICATION=...
INTERNAL_SERVICE_TOKEN_LLM=...
INTERNAL_SERVICE_TOKEN_OPS=...
DATABASE_URL=postgresql+psycopg://...
REDIS_URL=redis://localhost:6379/0
PUBLIC_WEB_ORIGINS=http://localhost:8200,http://127.0.0.1:8200
```

LLM config (ingest-service):

```env
INGESTION_LLM_MODEL=...
INGESTION_LLM_BASE_URL=...
INGESTION_LLM_API_KEY=...
```

Worker tuning:

```env
INGESTION_TICK_SECONDS=2
REVIEW_APPLY_TICK_SECONDS=2
NOTIFICATION_TICK_SECONDS=30
ENABLE_NOTIFICATIONS=false
```

Optional Gmail fake-source overrides (ingest-service only):

```env
GMAIL_API_BASE_URL=http://127.0.0.1:8765/gmail/v1/users/me
GMAIL_OAUTH_TOKEN_URL=http://127.0.0.1:8765/oauth2/token
GMAIL_OAUTH_AUTHORIZE_URL=http://127.0.0.1:8765/oauth2/auth
```

## Preferred Local Startup

Use the launcher when you want the active development topology:

```bash
scripts/dev_stack.sh up
```

This path starts frontend plus all 5 services, applies migrations, and uses the current local dev port set.

## Manual Local Startup

```bash
docker compose up -d postgres redis
python -m alembic upgrade head
SERVICE_NAME=public RUN_MIGRATIONS=false PORT=8200 ./scripts/start_service.sh
SERVICE_NAME=input RUN_MIGRATIONS=false PORT=8201 ./scripts/start_service.sh
SERVICE_NAME=ingest RUN_MIGRATIONS=false PORT=8202 ./scripts/start_service.sh
SERVICE_NAME=review RUN_MIGRATIONS=false PORT=8203 ./scripts/start_service.sh
SERVICE_NAME=llm RUN_MIGRATIONS=false PORT=8205 ./scripts/start_service.sh
SERVICE_NAME=notification RUN_MIGRATIONS=false PORT=8204 ./scripts/start_service.sh
```

## Compose Startup

```bash
docker compose up --build
```

Expected services:

1. `postgres`
2. `redis`
3. `input-service`
4. `ingest-service`
5. `llm-service`
6. `review-service`
7. `notification-service`

Compose exposure model:

1. public host ports remain `8001 -> input-service` and `8000 -> review-service`
2. `ingest-service`, `llm-service`, and `notification-service` remain internal-only in default compose
3. use `docker-compose.dev.yml` for dev-only ingest/llm/notification host port mappings

## Health Checks

Manual / launcher path:

```bash
curl -s http://localhost:8201/health
curl -s http://localhost:8202/health
curl -s http://localhost:8205/health
curl -s http://localhost:8200/health
curl -s http://localhost:8204/health
```

Compose public path:

```bash
curl -s http://localhost:8001/health
curl -s http://localhost:8000/health
```

## Internal API Auth

`/internal/*` endpoints require service identity headers:

```http
X-Service-Name: ops
X-Service-Token: <INTERNAL_SERVICE_TOKEN_OPS>
```

## API Routing Suggestion

For local direct-run services:

1. `PUBLIC_API_BASE_URL=http://127.0.0.1:8200`
2. `INPUT_SERVICE_BASE_URL=http://127.0.0.1:8201`
3. `INGEST_SERVICE_BASE_URL=http://127.0.0.1:8202`
4. `REVIEW_SERVICE_BASE_URL=http://127.0.0.1:8203`
5. `NOTIFY_SERVICE_BASE_URL=http://127.0.0.1:8204`
6. `LLM_SERVICE_BASE_URL=http://127.0.0.1:8205`

For compose public host routing:

1. `PUBLIC_API_BASE_URL=http://127.0.0.1:8000`

## E2E Smoke

```bash
python scripts/smoke_real_sources_three_rounds.py \
  --public-api-base http://127.0.0.1:8200 \
  --report data/synthetic/ddlchange_160/qa/real_source_smoke_report.json
```

Closure pipeline:

```bash
python scripts/smoke_microservice_closure.py \
  --public-api-base http://127.0.0.1:8200 \
  --input-internal-base http://127.0.0.1:8201 \
  --review-internal-base http://127.0.0.1:8203 \
  --ingest-internal-base http://127.0.0.1:8202 \
  --notify-internal-base http://127.0.0.1:8204 \
  --llm-internal-base http://127.0.0.1:8205
```

SLO check:

```bash
python scripts/ops_slo_check.py \
  --input-internal-base http://127.0.0.1:8201 \
  --ingest-internal-base http://127.0.0.1:8202 \
  --llm-internal-base http://127.0.0.1:8205 \
  --review-internal-base http://127.0.0.1:8203 \
  --notify-internal-base http://127.0.0.1:8204 \
  --ops-token "${INTERNAL_SERVICE_TOKEN_OPS}" \
  --json
```

## Ownership Guard

Run ownership check in CI/local:

```bash
python scripts/check_table_ownership.py
python scripts/check_microservice_closure.py
python scripts/update_openapi_snapshots.py
```
