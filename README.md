# CalendarDIFF

CalendarDIFF now runs as a single backend process by default.

## Default runtime
- Backend: `services.app_api.main:app`
- Frontend: Next.js app in `frontend/`
- Infra: PostgreSQL + Redis
- Default ports:
  - Backend `8200`
  - Frontend `3000`
  - PostgreSQL `5432`
  - Redis `6379`

Legacy split-service entrypoints are removed from the default repository path. The repo no longer treats `input/ingest/review/notification/llm` as separately launched services.

## Local setup
1. Copy `.env.example` to `.env` and fill in the required values.
2. Install backend dependencies.
3. Install frontend dependencies with `cd frontend && npm install`.
4. Start the default stack:

```bash
./scripts/dev_stack.sh up
```

Useful commands:

```bash
./scripts/dev_stack.sh status
./scripts/dev_stack.sh logs backend
./scripts/dev_stack.sh logs frontend
./scripts/dev_stack.sh down
./scripts/dev_stack.sh down --infra
./scripts/dev_stack.sh reset
```

Health check:

```bash
curl http://127.0.0.1:8200/health
```

## Direct backend run
```bash
SERVICE_NAME=backend RUN_MIGRATIONS=true PORT=8200 ./scripts/start_service.sh
```

`SERVICE_NAME` only accepts `backend`.

## Public HTTP surface
- `/auth/*`
- `/settings/profile`
- `/sources/*`
- `/changes*`
- `/families*`
- `/manual/events*`
- `/onboarding/*`
- `/health`

## OpenAPI
A single canonical snapshot is maintained at:

```text
contracts/openapi/public-service.json
```

Refresh it with:

```bash
python scripts/update_openapi_snapshots.py
```

## Worker model
The monolith still runs the ingest, review-apply, notification, and llm worker loops internally. Those loops are background tasks within the backend process, not separate services.

Worker enable flags remain:
- `INGEST_SERVICE_ENABLE_WORKER`
- `REVIEW_SERVICE_ENABLE_APPLY_WORKER`
- `NOTIFICATION_SERVICE_ENABLE_WORKER`
- `LLM_SERVICE_ENABLE_WORKER`

## Optional integrations
The repo still supports Gmail OAuth, Canvas ICS, SMTP delivery, fixture builders, and probe scripts. Those assets remain available, but they are not part of the default runtime story.

## Verification baseline
Backend regression:

```bash
pytest tests/test_core_ingest_gmail_directive_apply.py \
  tests/test_core_ingest_apply_calendar_delta.py \
  tests/test_input_gmail_source_api.py \
  tests/test_input_ics_source_api.py \
  tests/test_input_oauth_service.py \
  tests/test_onboarding_flow_api.py \
  tests/test_review_*.py \
  tests/test_manual_events_api.py \
  tests/test_course_work_item_families_api.py \
  tests/test_course_raw_types_api.py \
  tests/test_users_timezone_api.py \
  tests/test_openapi_contract_snapshots.py \
  tests/test_runtime_entrypoints.py
```

Frontend regression:

```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```
