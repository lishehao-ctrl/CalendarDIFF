# Frontend Console + Dev Launcher Release / Acceptance Guide

## Release Summary

This release combines two local-development deliverables into one acceptance package:

1. frontend console: commit `b1b8e67` (`feat: add calendardiff frontend console`)
2. full-stack local launcher: commit `a914101` (`chore: add local full-stack dev launcher`)

Together they provide:

1. a standalone `frontend/` Next.js console for CalendarDIFF
2. a single-command local stack launcher for `frontend + input + review + ingest + notification + llm + postgres + redis`
3. an acceptance path that no longer requires manually starting services one by one

## What Is Included

### Frontend Console

Routes:

1. `/` — Overview / onboarding hub
2. `/sources` — sources and sync control
3. `/review/changes` — review inbox
4. `/review/links` — link review workspace
5. `/settings` — user settings

Behavior:

1. browser requests go through Next route handlers, not directly to Python services
2. `/review/*` routes proxy to `review-service`
3. current MVP routes proxy all other public UI requests to `input-service`
4. Gmail remains visible in UI, but real OAuth connect is intentionally blocked in this release

### Local Dev Launcher

Script:

```bash
scripts/dev_stack.sh
```

Supported commands:

```bash
scripts/dev_stack.sh up
scripts/dev_stack.sh down
scripts/dev_stack.sh down --infra
scripts/dev_stack.sh status
scripts/dev_stack.sh logs frontend
scripts/dev_stack.sh logs all
```

Behavior:

1. `up` starts `postgres` and `redis` through `docker compose`
2. `up` applies schema with `python -m alembic upgrade head`
3. `up` starts `input`, `review`, `ingest`, `notification`, `llm`, and `frontend`
4. `status` reports infra reachability plus per-process health/pid/log path
5. `down` stops only the app layer
6. `down --infra` additionally stops this repo's compose-managed `postgres` and `redis`
7. logs and pid files are written to `output/dev-stack/`

## Prerequisites

Required before acceptance:

1. root `.env` exists and contains valid app/database/redis/LLM settings
2. `frontend/node_modules` exists
3. `docker compose` is available
4. local ports are free unless intentionally already in use by this stack:
   - `3000`, `8000`, `8001`, `8002`, `8004`, `8005`, `5432`, `6379`

Recommended bootstrap:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
cd frontend && npm install && cd ..
```

## Acceptance Procedure

### 1. Start the full stack

```bash
scripts/dev_stack.sh up
```

Expected result:

1. command exits successfully
2. it prints frontend URL and backend health URLs
3. `scripts/dev_stack.sh status` shows all six applications as `healthy`

### 2. Verify health endpoints

Expected HTTP `200`:

1. `http://127.0.0.1:3000`
2. `http://127.0.0.1:8000/health`
3. `http://127.0.0.1:8001/health`
4. `http://127.0.0.1:8002/health`
5. `http://127.0.0.1:8004/health`
6. `http://127.0.0.1:8005/health`

### 3. Frontend walkthrough

Open:

1. `http://127.0.0.1:3000/`
2. `http://127.0.0.1:3000/sources`
3. `http://127.0.0.1:3000/review/changes`
4. `http://127.0.0.1:3000/review/links`
5. `http://127.0.0.1:3000/settings`

Minimum UI checks:

1. Overview loads without requiring manual per-service startup
2. Sources page lists existing sources or empty state correctly
3. Creating an ICS source from the UI succeeds
4. Manual sync can be triggered from Sources
5. Review pages render loading / empty / populated states without route failure
6. Settings page can read and save user profile fields
7. Mobile navigation opens as a sheet on narrow screens

### 4. Launcher operability

Validate:

```bash
scripts/dev_stack.sh status
scripts/dev_stack.sh logs frontend
scripts/dev_stack.sh logs input
```

Expected result:

1. `status` shows per-service pid, health, and log path
2. `logs <service>` tails the correct log file

### 5. Shutdown

Application layer only:

```bash
scripts/dev_stack.sh down
```

Then verify app ports are released:

1. `3000`
2. `8000`
3. `8001`
4. `8002`
5. `8004`
6. `8005`

Optional infra shutdown:

```bash
scripts/dev_stack.sh down --infra
```

Expected result:

1. compose-managed `postgres` and `redis` stop
2. if another unrelated local instance already owns `5432` or `6379`, that external instance may still remain reachable

## Acceptance Criteria

The release is accepted when all of the following are true:

1. `scripts/dev_stack.sh up` brings the full local stack to a usable state from a clean shell
2. frontend UI is reachable at `http://127.0.0.1:3000`
3. all five backend services return healthy status
4. frontend can proxy successfully to both `input-service` and `review-service`
5. `scripts/dev_stack.sh status` reports healthy application state during runtime
6. `scripts/dev_stack.sh down` stops the app layer cleanly
7. `scripts/dev_stack.sh down --infra` stops compose-managed infra cleanly

## Known Limitations

1. this launcher is for local development and acceptance only; it is not a production deployment tool
2. Gmail OAuth is intentionally not part of this frontend MVP; the UI keeps Gmail visible but disabled
3. `down --infra` only stops this repo's `docker compose` services; it does not stop unrelated external local containers or services using the same ports
4. frontend uses polling-based file watching in the launcher to reduce local `EMFILE` watcher failures on this machine
5. some review evidence previews can still return backend `404` if the underlying seeded/test change has no persisted evidence file; the UI should still present a controlled error state

## Rollback Reference

If this release needs to be split apart again:

1. frontend-only baseline is available in commit `b1b8e67`
2. launcher/docs addition is isolated in commit `a914101`

That means the launcher can be reverted independently of the frontend UI if needed.
