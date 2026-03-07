# CalendarDIFF

CalendarDIFF runs as 5 services with shared PostgreSQL + Redis and event-driven domain boundaries.

Core flow:

1. ingest input sources (Canvas ICS/Gmail) and build event observations
2. ICS uses RFC-based delta detection first; only changed VEVENT components go to LLM
3. removed/cancelled ICS components are handled as deterministic removals
4. ICS canonical fields (`title/start/end/status/location`) stay deterministic from parser/source
5. LLM outputs enrichment only (`course_parse`, `event_parts`, `link_signals`), not canonical identity fields
6. `course_parse` is LLM-only (no local regex/raw text fallback in review/apply)
7. strong/weak naming uses 5 parsed parts (`dept/number/suffix/quarter/year2`) with monotonic best-name updates
8. cross-source linker uses inventory-state rules (`dept+number`, suffix/index constraints) and persists normalized links/candidates/blocks
9. candidate review stays out of pending-notification chain; notify remains canonical-change-only
10. link-candidate APIs: `GET /review/link-candidates`, `POST /review/link-candidates/{id}/decisions`, `GET/DELETE /review/link-candidates/blocks*`
11. build pending review proposals from source canonical observations
12. approve proposals into canonical events
13. enqueue and send digest notifications
14. allow manual due correction when parsed result is wrong

## Runtime Topology (5 Services + PostgreSQL + Redis)

1. `input-service` (`services.input_api.main:app`)
2. `ingest-service` (`services.ingest_api.main:app`)
3. `llm-service` (`services.llm_api.main:app`)
4. `review-service` (`services.review_api.main:app`)
5. `notification-service` (`services.notification_api.main:app`)
6. `postgres`
7. `redis`

## Quick Start

Current implementation guides:

- `docs/frontend_console_release_acceptance.md`
- `docs/deploy_three_layer_runtime.md`

1. Create environment and install dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
cd frontend && npm install && cd ..
```

2. Start the full local development stack:

```bash
scripts/dev_stack.sh up
```

This local launcher will:

1. start `postgres` and `redis` via `docker compose`
2. apply schema with `python -m alembic upgrade head`
3. start `frontend`, `input-service`, `ingest-service`, `llm-service`, `review-service`, and `notification-service`
4. write pid/log files under `output/dev-stack/`
5. keep PostgreSQL and Redis running unless you explicitly stop them with `scripts/dev_stack.sh down --infra`
6. support `scripts/dev_stack.sh reset` to stop the app layer, reset the configured PostgreSQL database to migration head, and restart the full local stack

`down --infra` only stops the `postgres` and `redis` services defined in this repo's `docker compose` files. It does not stop unrelated local instances already bound to the same ports.

Helpful follow-up commands:

```bash
scripts/dev_stack.sh status
scripts/dev_stack.sh logs frontend
scripts/dev_stack.sh logs all
scripts/dev_stack.sh reset
scripts/dev_stack.sh down
scripts/dev_stack.sh down --infra
```

### Manual Service Startup

If you want to run services one by one instead of using the local launcher:

```bash
docker compose up -d postgres redis
python -m alembic upgrade head
SERVICE_NAME=input RUN_MIGRATIONS=false PORT=8201 ./scripts/start_service.sh
SERVICE_NAME=ingest RUN_MIGRATIONS=false PORT=8202 ./scripts/start_service.sh
SERVICE_NAME=llm RUN_MIGRATIONS=false PORT=8205 ./scripts/start_service.sh
SERVICE_NAME=review RUN_MIGRATIONS=false PORT=8200 ./scripts/start_service.sh
SERVICE_NAME=notification RUN_MIGRATIONS=false PORT=8204 ./scripts/start_service.sh
cd frontend && INPUT_BACKEND_BASE_URL=http://127.0.0.1:8201 REVIEW_BACKEND_BASE_URL=http://127.0.0.1:8200 BACKEND_API_KEY="$APP_API_KEY" npm run dev -- --hostname 127.0.0.1 --port 3000
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

For the preferred local launcher, use `scripts/dev_stack.sh up` and the `820x` port set instead.

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
PUBLIC_WEB_ORIGINS=http://localhost:8200,http://127.0.0.1:8200
```

Ingestion LLM (chat/completions only):

```env
APP_LLM_OPENAI_MODEL=
INGESTION_LLM_MODEL=
INGESTION_LLM_BASE_URL=
INGESTION_LLM_API_KEY=
```

OAuth runtime config (single source of truth for route/base/redirect/key source):

```env
# Priority for OAuth public base URL:
# OAUTH_PUBLIC_BASE_URL > APP_BASE_URL > INPUT_API_BASE_URL > http://localhost:8201
OAUTH_PUBLIC_BASE_URL=http://localhost:8201
OAUTH_ROUTE_PREFIX=
OAUTH_SESSION_ROUTE_TEMPLATE=/sources/{source_id}/oauth-sessions
OAUTH_CALLBACK_ROUTE_TEMPLATE=/oauth/callbacks/{provider}
OAUTH_CALLBACK_REQUIRE_API_KEY=false
OAUTH_STATE_TTL_MINUTES=10
# Optional override; falls back to APP_SECRET_KEY.
OAUTH_TOKEN_ENCRYPTION_KEY=
GMAIL_OAUTH_SCOPE=https://www.googleapis.com/auth/gmail.readonly
GMAIL_OAUTH_ACCESS_TYPE=offline
GMAIL_OAUTH_PROMPT=consent
GMAIL_OAUTH_INCLUDE_GRANTED_SCOPES=true
```

Input-service startup now logs effective OAuth runtime values:

1. final Gmail redirect URI
2. registered callback routes
3. OAuth key-source (`OAUTH_TOKEN_ENCRYPTION_KEY` or `APP_SECRET_KEY`)

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

Notification sink mode:

```env
# smtp (default) or jsonl (for local demo without real email side effects)
NOTIFY_SINK_MODE=smtp
NOTIFY_JSONL_PATH=data/smoke/notify_sink.jsonl
```

Optional per-service base URLs (useful when services run on different ports):

```env
INPUT_API_BASE_URL=http://localhost:8201
REVIEW_API_BASE_URL=http://localhost:8200
INGEST_API_BASE_URL=http://localhost:8202
NOTIFY_API_BASE_URL=http://localhost:8204
```

## Internal Ops Auth

`/internal/*` endpoints no longer accept `X-API-Key`.

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
curl -s http://localhost:8201/health
curl -s http://localhost:8202/health
curl -s http://localhost:8205/health
curl -s http://localhost:8200/health
curl -s http://localhost:8204/health
```

## Real Source Smoke (3 Rounds)

```bash
python scripts/smoke_real_sources_three_rounds.py \
  --input-api-base http://127.0.0.1:8201 \
  --review-api-base http://127.0.0.1:8200 \
  --report data/synthetic/ddlchange_160/qa/real_source_smoke_report.json
```

## Semester Demo Smoke (3 Semesters × 10 Batches × 10 Items/Source)

Use online LLM + local JSONL notification sink. This flow does not require Gmail OAuth; `provider=gmail` is backed by the semester fake inbox provider.

```bash
NOTIFY_SINK_MODE=jsonl \
NOTIFY_JSONL_PATH=data/smoke/notify_sink.jsonl \
python scripts/smoke_semester_demo.py \
  --input-api-base http://127.0.0.1:8201 \
  --review-api-base http://127.0.0.1:8200 \
  --ingest-api-base http://127.0.0.1:8202 \
  --notify-api-base http://127.0.0.1:8204 \
  --llm-api-base http://127.0.0.1:8205 \
  --ops-token "${INTERNAL_SERVICE_TOKEN_OPS}" \
  --notification-jsonl data/smoke/notify_sink.jsonl \
  --report data/synthetic/semester_demo/qa/semester_demo_report.json
```

Notification-service exposes a test-only internal flush used by the runner:

```http
POST /internal/notifications/flush
X-Service-Name: ops
X-Service-Token: <INTERNAL_SERVICE_TOKEN_OPS>
```

Online pytest wrapper:

```bash
RUN_SEMESTER_DEMO_SMOKE=true \
SEMESTER_DEMO_NOTIFICATION_JSONL=data/smoke/notify_sink.jsonl \
pytest -q tests/test_semester_demo_online.py
```

Full closure check:

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
  --review-base http://127.0.0.1:8200 \
  --notify-base http://127.0.0.1:8204 \
  --llm-base http://127.0.0.1:8205 \
  --ops-token "${INTERNAL_SERVICE_TOKEN_OPS}" \
  --json
```

OpenAPI snapshots:

```bash
python scripts/update_openapi_snapshots.py
```

## Local Quality Checks

Run in this order:

```bash
mypy .
flake8 .
python -m build
```

Notes:

1. `mypy` uses `explicit_package_bases` so `services/*/main.py` no longer collides as duplicate top-level `main`.
2. `flake8` excludes local environment/vendor/history-heavy paths (for example `.venv`, `tools`, `app/db/migrations`) to keep output focused on active runtime code.
3. `python -m build` requires the `build` package, included in `requirements.txt` and `project.optional-dependencies.dev`.

## API Surface

Detailed snapshot:

1. `docs/api_surface_current.md`
2. `docs/event_contracts.md`

## Manual Due Correction

When the parser extracts an incorrect due time, review-service supports direct canonical correction APIs:

1. `POST /review/corrections/preview`
2. `POST /review/corrections`

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

1. `docs/frontend_console_release_acceptance.md`
2. `docs/deploy_three_layer_runtime.md`
3. `docs/architecture.md`
4. `docs/api_surface_current.md`
5. `docs/service_table_ownership.md`
6. `docs/event_contracts.md`
7. `docs/ops_microservice_slo.md`
8. `docs/dataflow_input_to_notification.md`
9. `docs/archive/README.md`
