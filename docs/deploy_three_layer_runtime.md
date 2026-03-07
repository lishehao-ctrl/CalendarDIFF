# Deploy Microservice Runtime (Shared PostgreSQL)

## Goal

Run backend as 5 microservices plus PostgreSQL + Redis:

1. input-service
2. ingest-service
3. llm-service
4. review-service
5. notification-service
6. postgres
7. redis

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

## Local Startup (Manual)

1. migrate DB:

```bash
alembic upgrade head
```

Migration revision rename handling:

1. reset + upgrade (preferred for local/dev):

```bash
scripts/reset_postgres_db.sh
alembic upgrade head
```

2. remap current revision and then upgrade (for existing DB state):

```sql
UPDATE alembic_version
SET version_num = '20260302_0004_src_bridge_map'
WHERE version_num LIKE '20260302_0004_src_%_map'
  AND version_num <> '20260302_0004_src_bridge_map';
```

```bash
alembic upgrade head
```

2. start services:

```bash
SERVICE_NAME=input PORT=8201 ./scripts/start_service.sh
SERVICE_NAME=ingest PORT=8202 ./scripts/start_service.sh
SERVICE_NAME=llm PORT=8205 ./scripts/start_service.sh
SERVICE_NAME=review PORT=8200 ./scripts/start_service.sh
SERVICE_NAME=notification PORT=8204 ./scripts/start_service.sh
```

## Local Startup (Compose)

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

Default exposure model:

1. public: `input-service` (`8001`), `review-service` (`8000`)
2. internal-only: `ingest-service`, `llm-service`, `notification-service`
3. use `docker-compose.dev.yml` for dev-only ingest/llm/notification host port mappings

## Health Checks

```bash
curl -s http://localhost:8201/health
curl -s http://localhost:8202/health
curl -s http://localhost:8205/health
curl -s http://localhost:8200/health
curl -s http://localhost:8204/health
```

## Internal API Auth

`/internal/*` endpoints require service identity headers:

```http
X-Service-Name: ops
X-Service-Token: <INTERNAL_SERVICE_TOKEN_OPS>
```

Import smoke:

```bash
python -c "import services.input_api.main"
python -c "import services.ingest_api.main"
python -c "import services.llm_api.main"
python -c "import services.review_api.main"
python -c "import services.notification_api.main"
```

## API Routing Suggestion

Because services are direct-exposed, client should configure per-domain base URLs:

1. `INPUT_API_BASE_URL=http://127.0.0.1:8201`
2. `INGEST_API_BASE_URL=http://127.0.0.1:8202` (internal ops)
3. `LLM_API_BASE_URL=http://127.0.0.1:8205` (internal ops)
4. `REVIEW_API_BASE_URL=http://127.0.0.1:8200`
5. `NOTIFY_API_BASE_URL=http://127.0.0.1:8204` (internal ops)

## E2E Smoke

```bash
python scripts/smoke_real_sources_three_rounds.py \
  --input-api-base http://127.0.0.1:8201 \
  --review-api-base http://127.0.0.1:8200 \
  --report data/synthetic/ddlchange_160/qa/real_source_smoke_report.json
```

Closure pipeline:

```bash
python scripts/smoke_microservice_closure.py \
  --input-api-base http://127.0.0.1:8201 \
  --review-api-base http://127.0.0.1:8200 \
  --ingest-api-base http://127.0.0.1:8202 \
  --notify-api-base http://127.0.0.1:8204 \
  --llm-api-base http://127.0.0.1:8205
```

SLO check:

```bash
python scripts/ops_slo_check.py \
  --input-base http://127.0.0.1:8201 \
  --ingest-base http://127.0.0.1:8202 \
  --llm-base http://127.0.0.1:8205 \
  --review-base http://127.0.0.1:8200 \
  --notify-base http://127.0.0.1:8204 \
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
