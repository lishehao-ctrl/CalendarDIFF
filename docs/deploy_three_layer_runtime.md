# Deploy Three-Layer Runtime

## Goal

Run backend with exactly three runtime units plus PostgreSQL:

1. API (`app.main`)
2. Ingestion worker (`services.ingestion_runtime.worker`)
3. Notification worker (`services.notification.worker`)

## Prerequisites

1. `.env` configured with DB and app secrets
2. PostgreSQL reachable from all runtime units
3. schema migrated to head (`alembic upgrade head`)

## Environment

Required:

```env
APP_API_KEY=...
APP_SECRET_KEY=...
DATABASE_URL=postgresql+psycopg://...
```

Recommended worker tuning:

```env
INGESTION_TICK_SECONDS=2
NOTIFICATION_TICK_SECONDS=30
ENABLE_NOTIFICATIONS=false
```

LLM config for ingestion parsers:

```env
INGESTION_LLM_MODEL=...
INGESTION_LLM_BASE_URL=...
INGESTION_LLM_API_KEY=...
```

## Local Startup (Manual)

1. migrate DB:

```bash
alembic upgrade head
```

2. start API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

3. start ingestion worker:

```bash
python -m services.ingestion_runtime.worker
```

4. start notification worker:

```bash
python -m services.notification.worker
```

## Local Startup (Compose)

```bash
docker compose up --build
```

Expected services:

1. `postgres`
2. `api`
3. `ingestion-worker`
4. `notification-worker`

## Health Checks

1. API health:

```bash
curl -s http://localhost:8000/health
```

2. Import smoke:

```bash
python -c "import app.main"
python -c "import services.ingestion_runtime.worker"
python -c "import services.notification.worker"
```

3. Ingestion worker log fields per tick:

`worker_id`, `orchestrated_count`, `connector_processed`, `apply_processed`, `latency_ms`

4. Notification worker log fields per tick:

`processed_slots`, `sent_count`, `failed_count`, `tick_latency_ms`

## Failure Triage

1. `ModuleNotFoundError: app.state`
   - ensure deployment uses `app.main:app` and does not reference removed legacy service entrypoints.
2. `scheduler_tick_seconds` attribute errors
   - ensure ingestion runtime uses `INGESTION_TICK_SECONDS` and `services.ingestion_runtime.worker`.
3. schema mismatch (`503` on `/health`)
   - run clean migration chain and verify current head.
