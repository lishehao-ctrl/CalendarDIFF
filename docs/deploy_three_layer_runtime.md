# Deploy Monolith Runtime (Shared PostgreSQL)

## Goal

Run backend as one monolith API process plus PostgreSQL and Redis:

1. backend-service
2. postgres
3. redis

## Current Runtime Notes

1. local launcher flow uses `3000 / 8200`
2. compose host exposure remains a separate compatibility path and may expose different host ports
3. public dashboard traffic is session-based and enters through the frontend, not by anonymously calling backend APIs
4. backend-service owns source lifecycle, OAuth session/callback, onboarding, review, notification, and user profile APIs

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

LLM config (backend-service workers):

```env
INGESTION_LLM_MODEL=...
INGESTION_LLM_API_MODE=responses
INGESTION_LLM_BASE_URL=...
INGESTION_LLM_API_KEY=...
INGESTION_LLM_EXTRA_BODY_JSON=
INGESTION_LLM_TIMEOUT_SECONDS=
INGESTION_LLM_MAX_RETRIES=
INGESTION_LLM_MAX_INPUT_CHARS=
```

Default compose treats `INGESTION_LLM_MODEL`, `INGESTION_LLM_BASE_URL`, and `INGESTION_LLM_API_KEY` as required and fails fast during `docker compose config/up` if any are blank. `INGESTION_LLM_API_MODE` selects whether the gateway talks to `/responses` or `/chat/completions`.

Worker tuning:

```env
INGESTION_TICK_SECONDS=2
REVIEW_APPLY_TICK_SECONDS=2
NOTIFICATION_TICK_SECONDS=5
ENABLE_NOTIFICATIONS=false
```

Optional Gmail fake-source overrides:

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

Default compose mounts `HOST_SECRETS_DIR` read-only into the backend container. Keep the client secrets file under that directory, outside the repository, and run `chmod 600` on the file.

## Preferred Local Startup

Use the launcher when you want the active development topology:

```bash
scripts/dev_stack.sh up
```

This path starts the frontend and the monolith backend-service, applies migrations, and uses the current local dev port set.

## Manual Local Startup

```bash
docker compose up -d postgres redis
python -m alembic upgrade head
SERVICE_NAME=public RUN_MIGRATIONS=false PORT=8200 ./scripts/start_service.sh
SERVICE_NAME=backend RUN_MIGRATIONS=false PORT=8200 ./scripts/start_service.sh
```

## Compose Startup

```bash
docker compose up --build
```

Expected services:

1. `postgres`
2. `redis`
3. `public-service` (monolith backend)
4. `frontend`

Compose exposure model:

1. `frontend` is exposed on `localhost:3000`
2. `public-service` is exposed on `localhost:8000`
3. legacy split services are available only under the `legacy` compose profile
4. when Gmail OAuth is enabled, the backend container mounts `HOST_SECRETS_DIR` read-only

## Health Checks

Manual / launcher path:

```bash
curl -s http://localhost:8200/health
```

Compose public path:

```bash
curl -s http://localhost:3000/login
curl -s http://localhost:8000/health
```

## API Routing Suggestion

1. local direct-run backend: `PUBLIC_API_BASE_URL=http://127.0.0.1:8200`
2. compose public host routing: `PUBLIC_API_BASE_URL=http://127.0.0.1:8000`

## E2E Smoke

```bash
python scripts/smoke_real_sources_three_rounds.py \
  --public-api-base http://127.0.0.1:8200 \
  --report data/synthetic/ddlchange_160/qa/real_source_smoke_report.json
```

## Ownership Guard

Run ownership check in CI/local:

```bash
python scripts/check_table_ownership.py
python scripts/check_microservice_closure.py
python scripts/update_openapi_snapshots.py
```
