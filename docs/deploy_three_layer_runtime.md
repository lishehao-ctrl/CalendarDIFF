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

## Nginx Live Routing

Before editing live host Nginx for CalendarDIFF, read `docs/nginx_live_routing_architecture.md`.

CalendarDIFF live routing assumes:

1. `cal.shehao.app` is the only domain owned by this app on the host
2. frontend page traffic terminates at `127.0.0.1:3000`
3. OAuth callbacks and `/health` terminate at `127.0.0.1:8000`
4. shared websocket upgrade helpers live in `conf.d`, not inside an unrelated site file
5. CalendarDIFF should not depend on a mixed-purpose `default` site block

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

LLM config (ingest-service / llm-service):

```env
INGESTION_LLM_MODEL=...
INGESTION_LLM_BASE_URL=...
INGESTION_LLM_API_KEY=...
```

Default compose treats those three variables as required and fails fast during `docker compose config/up` if any are blank.

Worker tuning:

```env
INGESTION_TICK_SECONDS=2
REVIEW_APPLY_TICK_SECONDS=2
NOTIFICATION_TICK_SECONDS=5
ENABLE_NOTIFICATIONS=false
```

Optional Gmail fake-source overrides (ingest-service only):

```env
GMAIL_API_BASE_URL=http://127.0.0.1:8765/gmail/v1/users/me
GMAIL_OAUTH_TOKEN_URL=http://127.0.0.1:8765/oauth2/token
GMAIL_OAUTH_AUTHORIZE_URL=http://127.0.0.1:8765/oauth2/auth
```

For real Gmail OAuth under Docker Compose, also set:

```env
HOST_SECRETS_DIR=/absolute/path/outside-repo
GMAIL_OAUTH_CLIENT_SECRETS_FILE=/absolute/path/outside-repo/google_client_secret.json
```

Default compose mounts `HOST_SECRETS_DIR` read-only into `public-service` and `ingest-service` at the same absolute path. Keep the client secrets file under that directory, outside the repository, and run `chmod 600` on the file.

## Preferred Local Startup

Use the launcher when you want the active development topology:

```bash
scripts/dev_stack.sh up
```

This path starts the frontend, `public-service`, and the 5 internal services, applies migrations, and uses the current local dev port set.

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
3. `public-service`
4. `input-service`
5. `ingest-service`
6. `llm-service`
7. `review-service`
8. `notification-service`
9. `frontend`

Compose exposure model:

1. `frontend` is exposed on `localhost:3000`
2. `public-service` is exposed on `localhost:8000`
3. `input-service`, `review-service`, `ingest-service`, `llm-service`, and `notification-service` remain internal-only in default compose
4. when Gmail OAuth is enabled, `public-service` and `ingest-service` mount `HOST_SECRETS_DIR` read-only so both services can read the same Google client secrets file
5. use `docker-compose.dev.yml` for dev-only internal service host port mappings

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
curl -s http://localhost:3000/login
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
