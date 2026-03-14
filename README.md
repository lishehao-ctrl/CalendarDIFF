# CalendarDIFF

[![Language: English](https://img.shields.io/badge/Language-English-2ea44f)](./README.md)
[![Language: 中文](https://img.shields.io/badge/Language-%E4%B8%AD%E6%96%87-0ea5e9)](./README.zh-CN.md)

Live app: [cal.shehao.app](https://cal.shehao.app)

CalendarDIFF is a semantic-first deadline inbox for students who need one trustworthy place to reconcile coursework from multiple sources.


## Overview

Instead of treating every source as ground truth, CalendarDIFF:

1. ingests source records from Canvas ICS and Gmail
2. normalizes them into source observations
3. proposes semantic changes
4. lets users review and approve the final state



## Highlights

1. Multi-source reconciliation
   Combine Canvas ICS and Gmail into one reviewable deadline inbox.

2. Semantic-first identity
   Internal identity is stable via `entity_uid`, while user-facing display stays intuitive with `course + family + ordinal`.

3. Review before commit
   Incoming source data becomes pending `changes`; only approved changes update `event_entities`.

4. Delta-first ingestion
   ICS uses RFC-based delta detection so only changed VEVENT components go through expensive parsing.

5. Frozen evidence
   Review previews remain readable even after source data changes.

6. Manual correction path
   Users can directly correct due dates when parser output is imperfect.

7. Notification-ready
   New pending changes can immediately trigger review notifications.

## Core Flow

High-level flow

1. ingest input sources and build source observations  
2. apply deterministic ICS delta handling first  
3. send only changed records to LLM parsing  
4. generate pending review proposals in `changes`  
5. approve proposals into `event_entities`  
6. send review notifications  

Key runtime rules

1. ICS canonical fields such as `title/start/end/status/location` remain parser/source-deterministic.  
2. LLM contributes semantic enrichment such as course parsing, event parts, and link signals.  
3. Candidate link review is separate from the canonical pending-notification chain.  
4. Approved semantic state lives in `event_entities`.  

## Runtime Topology

Current runtime

1. `public-service` (`services.public_api.main:app`)
2. `input-service` (`services.input_api.main:app`, internal metrics/runtime only)
3. `ingest-service` (`services.ingest_api.main:app`)
4. `llm-service` (`services.llm_api.main:app`)
5. `review-service` (`services.review_api.main:app`, internal apply/runtime only)
6. `notification-service` (`services.notification_api.main:app`)
7. `postgres`
8. `redis`

Public traffic goes through the unified public gateway, while internal services handle ingest, parsing, review, and notification work.


## Quick Start

Useful guides

- `docs/frontend_console_release_acceptance.md`
- `docs/deploy_three_layer_runtime.md`
- `docs/nginx_live_routing_architecture.md`
- `docs/architecture.md`

### 1. Install Dependencies

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
cd frontend && npm install && cd ..
```

### 2. Start the Full Local Stack

```bash
scripts/dev_stack.sh up
```

This launcher will

1. start `postgres` and `redis` via `docker compose`
2. apply schema with `python -m alembic upgrade head`
3. start `frontend`, `public-service`, `input-service`, `ingest-service`, `llm-service`, `review-service`, and `notification-service`
4. write pid/log files under `output/dev-stack/`
5. keep PostgreSQL and Redis running unless you explicitly stop them with `scripts/dev_stack.sh down --infra`
6. support `scripts/dev_stack.sh reset` to reset the configured database and restart the stack

`down --infra` only stops the `postgres` and `redis` services defined in this repo. It does not stop unrelated local instances already using the same ports.


Helpful commands

```bash
scripts/dev_stack.sh status
scripts/dev_stack.sh logs frontend
scripts/dev_stack.sh logs all
scripts/dev_stack.sh reset
scripts/dev_stack.sh down
scripts/dev_stack.sh down --infra
```

### 3. Manual Startup

If you want to run services one by one

```bash
docker compose up -d postgres redis
python -m alembic upgrade head
SERVICE_NAME=public RUN_MIGRATIONS=false PORT=8200 ./scripts/start_service.sh
SERVICE_NAME=input RUN_MIGRATIONS=false PORT=8201 ./scripts/start_service.sh
SERVICE_NAME=ingest RUN_MIGRATIONS=false PORT=8202 ./scripts/start_service.sh
SERVICE_NAME=review RUN_MIGRATIONS=false PORT=8203 ./scripts/start_service.sh
SERVICE_NAME=llm RUN_MIGRATIONS=false PORT=8205 ./scripts/start_service.sh
SERVICE_NAME=notification RUN_MIGRATIONS=false PORT=8204 ./scripts/start_service.sh
cd frontend && BACKEND_BASE_URL=http://127.0.0.1:8200 BACKEND_API_KEY="$APP_API_KEY" NEXT_DIST_DIR=.next-dev npm run dev -- --hostname 127.0.0.1 --port 3000
```

## Docker Compose

Run the full local stack

```bash
docker compose up --build
```

Compose includes

1. `postgres`
2. `redis`
3. `public-service`
4. `input-service`
5. `ingest-service`
6. `llm-service`
7. `review-service`
8. `notification-service`
9. `frontend`

Default host ports

1. `frontend` on `localhost:3000`
2. `public-service` on `localhost:8000`

For day-to-day local work, prefer `scripts/dev_stack.sh up` and the `820x` port set.


`input-service`, `review-service`, `ingest-service`, `llm-service`, and `notification-service` are internal-only in default compose. Use `docker-compose.dev.yml` if you want internal port exposure for debugging.


If you enable Gmail OAuth under compose, set `HOST_SECRETS_DIR` to the parent directory of `GMAIL_OAUTH_CLIENT_SECRETS_FILE`.


## Core Environment Variables

### Required

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
PUBLIC_WEB_ORIGINS=http://localhost:8200,http://127.0.0.1:8200
```

### Ingestion LLM

```env
APP_LLM_OPENAI_MODEL=
INGESTION_LLM_MODEL=
INGESTION_LLM_API_MODE=responses
INGESTION_LLM_BASE_URL=
INGESTION_LLM_API_KEY=
INGESTION_LLM_EXTRA_BODY_JSON=
INGESTION_LLM_TIMEOUT_SECONDS=
INGESTION_LLM_MAX_RETRIES=
INGESTION_LLM_MAX_INPUT_CHARS=
```

CalendarDIFF's LLM gateway follows `INGESTION_LLM_API_MODE` and can talk to either `/responses` or `/chat/completions`. Under `docker compose`, `INGESTION_LLM_MODEL`, `INGESTION_LLM_BASE_URL`, and `INGESTION_LLM_API_KEY` are required. `INGESTION_LLM_EXTRA_BODY_JSON` is available for provider-specific passthrough options such as `{\"enable_thinking\":false}`, and the timeout / retry knobs can be tuned with `INGESTION_LLM_TIMEOUT_SECONDS`, `INGESTION_LLM_MAX_RETRIES`, and `INGESTION_LLM_MAX_INPUT_CHARS`.


### OAuth Runtime Config

```env
# Priority for OAuth public base URL:
# OAUTH_PUBLIC_BASE_URL > PUBLIC_API_BASE_URL > APP_BASE_URL > http://localhost:8200
OAUTH_PUBLIC_BASE_URL=http://localhost:8200
OAUTH_ROUTE_PREFIX=
OAUTH_SESSION_ROUTE_TEMPLATE=/sources/{source_id}/oauth-sessions
OAUTH_CALLBACK_ROUTE_TEMPLATE=/oauth/callbacks/{provider}
OAUTH_CALLBACK_REQUIRE_API_KEY=false
OAUTH_STATE_TTL_MINUTES=10
# Optional override; falls back to APP_SECRET_KEY.
OAUTH_TOKEN_ENCRYPTION_KEY=
HOST_SECRETS_DIR=/tmp/calendardiff-secrets
GMAIL_OAUTH_CLIENT_SECRETS_FILE=/tmp/calendardiff-secrets/google_client_secret.json
GMAIL_OAUTH_SCOPE=https://www.googleapis.com/auth/gmail.readonly
GMAIL_OAUTH_ACCESS_TYPE=offline
GMAIL_OAUTH_PROMPT=consent
GMAIL_OAUTH_INCLUDE_GRANTED_SCOPES=true
```

Input-service logs the effective OAuth runtime values on startup, including:

1. final Gmail redirect URI
2. registered callback routes
3. OAuth key source (`OAUTH_TOKEN_ENCRYPTION_KEY` or `APP_SECRET_KEY`)

### Optional Gmail Endpoint Overrides

```env
GMAIL_API_BASE_URL=http://127.0.0.1:8765/gmail/v1/users/me
GMAIL_OAUTH_TOKEN_URL=http://127.0.0.1:8765/oauth2/token
GMAIL_OAUTH_AUTHORIZE_URL=http://127.0.0.1:8765/oauth2/auth
```

### Worker Intervals

```env
INGESTION_TICK_SECONDS=2
LLM_SERVICE_ENABLE_WORKER=true
REVIEW_APPLY_TICK_SECONDS=2
NOTIFICATION_TICK_SECONDS=5
```

### Notification Sink Mode

```env
# smtp (default) or jsonl (for local demo without real email side effects)
NOTIFY_SINK_MODE=smtp
NOTIFY_JSONL_PATH=data/smoke/notify_sink.jsonl
```

### Real Gmail SMTP Notifications

Use this when you want real outgoing reminder emails.


```env
ENABLE_NOTIFICATIONS=true
NOTIFY_SINK_MODE=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USERNAME=your-account@gmail.com
SMTP_PASSWORD=<google-app-password>
SMTP_FROM_NAME=CalendarDIFF
SMTP_FROM_EMAIL=your-account@gmail.com
DEFAULT_NOTIFY_EMAIL=

APP_BASE_URL=https://cal.shehao.app
FRONTEND_APP_BASE_URL=https://cal.shehao.app
PUBLIC_WEB_ORIGINS=https://cal.shehao.app

NOTIFICATION_TICK_SECONDS=5
```

Operational notes

1. Gmail App Password requires 2-Step Verification.  
2. Keep `SMTP_USERNAME` and `SMTP_FROM_EMAIL` aligned unless you intentionally use aliases.  
3. `SMTP_FROM_NAME` controls the human-readable sender name.  
4. Turn on `ENABLE_NOTIFICATIONS=true` before expecting notification delivery.  

### Unified Public API Base URL

```env
BACKEND_BASE_URL=http://localhost:8200
```

## Internal Ops Auth

`/internal/*` endpoints no longer accept `X-API-Key`.


Use service-token headers

```http
X-Service-Name: ops
X-Service-Token: <INTERNAL_SERVICE_TOKEN_OPS>
```

Worker toggles

```env
INGEST_SERVICE_ENABLE_WORKER=true
REVIEW_SERVICE_ENABLE_APPLY_WORKER=true
NOTIFICATION_SERVICE_ENABLE_WORKER=true
ENABLE_NOTIFICATIONS=false
```

## Health Checks

```bash
curl -s http://localhost:8200/health
curl -s http://localhost:8201/health
curl -s http://localhost:8202/health
curl -s http://localhost:8203/health
curl -s http://localhost:8204/health
curl -s http://localhost:8205/health
```

## Smoke Tests

### Real Source Smoke

```bash
python scripts/smoke_real_sources_three_rounds.py \
  --public-api-base http://127.0.0.1:8200 \
  --report data/synthetic/ddlchange_160/qa/real_source_smoke_report.json
```

### Semester Demo Smoke

Use online LLM + local JSONL notification sink. This flow does not require Gmail OAuth.


```bash
NOTIFY_SINK_MODE=jsonl \
NOTIFY_JSONL_PATH=data/smoke/notify_sink.jsonl \
python scripts/smoke_semester_demo.py \
  --public-api-base http://127.0.0.1:8200 \
  --ingest-internal-base http://127.0.0.1:8202 \
  --notify-internal-base http://127.0.0.1:8204 \
  --llm-internal-base http://127.0.0.1:8205 \
  --ops-token "${INTERNAL_SERVICE_TOKEN_OPS}" \
  --notification-jsonl data/smoke/notify_sink.jsonl \
  --report data/synthetic/semester_demo/qa/semester_demo_report.json
```

Notification flush endpoint

```http
POST /internal/notifications/flush
X-Service-Name: ops
X-Service-Token: <INTERNAL_SERVICE_TOKEN_OPS>
```

Online pytest wrapper

```bash
RUN_SEMESTER_DEMO_SMOKE=true \
SEMESTER_DEMO_NOTIFICATION_JSONL=data/smoke/notify_sink.jsonl \
pytest -q tests/test_semester_demo_online.py
```

Full closure check

```bash
python scripts/smoke_microservice_closure.py \
  --public-api-base http://127.0.0.1:8200 \
  --input-internal-base http://127.0.0.1:8201 \
  --review-internal-base http://127.0.0.1:8203 \
  --ingest-internal-base http://127.0.0.1:8202 \
  --notify-internal-base http://127.0.0.1:8204 \
  --llm-internal-base http://127.0.0.1:8205
```

SLO check

```bash
python scripts/ops_slo_check.py \
  --input-internal-base http://127.0.0.1:8201 \
  --ingest-internal-base http://127.0.0.1:8202 \
  --review-internal-base http://127.0.0.1:8203 \
  --notify-internal-base http://127.0.0.1:8204 \
  --llm-internal-base http://127.0.0.1:8205 \
  --ops-token "${INTERNAL_SERVICE_TOKEN_OPS}" \
  --json
```

OpenAPI snapshots

```bash
python scripts/update_openapi_snapshots.py
```

## Review Model

Review-service supports both proposal review and direct canonical edit.


Key behavior

1. `POST /review/edits/preview`
2. `POST /review/edits` with `mode=canonical`
3. target can be provided by `change_id` or `entity_uid`
4. date-only `patch.due_at` is normalized to `23:59` in `users.timezone_name`
5. conflicting pending changes for the same `entity_uid` are auto-rejected
6. canonical edit writes an approved audit change and emits `review.decision.approved`

## Local Quality Checks

Run in this order

```bash
mypy .
flake8 .
python -m build
```

Notes

1. `mypy` uses `explicit_package_bases`, so `services/*/main.py` does not collide as duplicate top-level `main`.
2. `flake8` excludes environment/vendor/history-heavy paths such as `.venv`, `tools`, and `app/db/migrations`.
3. `python -m build` requires the `build` package, which is already included in `requirements.txt`.

## Testing

```bash
source .venv/bin/activate
python -m pytest -q
```

## API and Docs

API snapshots

1. `docs/api_surface_current.md`
2. `docs/event_contracts.md`

Core docs

1. `docs/frontend_console_release_acceptance.md`
2. `docs/deploy_three_layer_runtime.md`
3. `docs/architecture.md`
4. `docs/service_table_ownership.md`
5. `docs/ops_microservice_slo.md`
6. `docs/dataflow_input_to_notification.md`
7. `docs/archive/README.md`
