# CalendarDIFF

CalendarDIFF runs as a V2 ingestion and review platform with one canonical flow:

1. ingest input sources (ICS/Gmail) and parse with LLM
2. build pending review proposals from observations
3. approve proposals into canonical events
4. send digest notifications on schedule

## Runtime Topology (Three Layers)

The backend is intentionally collapsed to three runtime units:

1. Input layer: `ingestion-worker` (orchestrator + connector + core apply)
2. Review + DB layer: `api` (`app.main:app`) + PostgreSQL
3. Notification layer: `notification-worker` (digest sender)

There is no nginx gateway and no split control-plane/core API process.

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

4. Run API + workers (three processes):

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
python -m services.ingestion_runtime.worker
python -m services.notification.worker
```

5. Open UI:

```text
http://localhost:8000/ui
```

## Docker Compose

Run full local stack with one command:

```bash
docker compose up --build
```

Compose includes:

1. `postgres`
2. `api`
3. `ingestion-worker`
4. `notification-worker`

## Core Environment Variables

Required:

```env
APP_API_KEY=dev-api-key-change-me
APP_SECRET_KEY=7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk=
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff
```

Ingestion LLM (chat/completions only):

```env
INGESTION_LLM_MODEL=gpt-5.3-codex
INGESTION_LLM_BASE_URL=
INGESTION_LLM_API_KEY=
```

Worker intervals:

```env
INGESTION_TICK_SECONDS=2
NOTIFICATION_TICK_SECONDS=30
```

Notification control:

```env
ENABLE_NOTIFICATIONS=false
```

If `ENABLE_NOTIFICATIONS=false`, notification worker keeps polling loop but skips send.

## Health and Smoke Checks

```bash
curl -s http://localhost:8000/health
python -c "import app.main"
python -c "import services.ingestion_runtime.worker"
python -c "import services.notification.worker"
```

## API Surface (V2)

Main API groups:

1. onboarding + users
2. input sources + sync requests + oauth/webhooks
3. review pool (`/v2/review-items/changes`)
4. change/timeline reads (`/v2/change-events`, `/v2/timeline-events`)
5. health + UI routes

Detailed snapshot:

1. `docs/api_surface_current.md`

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
4. `docs/review_pool_unified_flow.md`
5. `docs/v2_llm_parser_placeholders.md`
