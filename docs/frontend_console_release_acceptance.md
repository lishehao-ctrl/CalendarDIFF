# Frontend Console + Dev Launcher Release / Acceptance Guide

## Summary

This guide covers the current local development and acceptance path for CalendarDIFF.

It assumes the active runtime shape:

1. frontend at `http://127.0.0.1:3000`
2. backend services at `8200 / 8201 / 8202 / 8203 / 8204 / 8205`
3. login-first dashboard access with session auth
4. Sources page using a single Canvas ICS link plus a single Gmail OAuth source per user

## What Is Included

### Frontend Console

Routes:

1. `/login`
2. `/register`
3. `/onboarding`
4. `/`
5. `/sources`
6. `/review/changes`
7. `/review/links`
8. `/settings`

Behavior:

1. browser requests go through Next route handlers, not directly to Python services
2. dashboard routes require an authenticated session
3. unauthenticated `/` redirects to `/login`
4. `/sources` manages one Canvas ICS link per user and one Gmail OAuth source per user
5. Overview shows structured source health instead of raw backend error text

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
scripts/dev_stack.sh reset
scripts/dev_stack.sh status
scripts/dev_stack.sh logs frontend
scripts/dev_stack.sh logs all
```

Behavior:

1. `up` starts `postgres` and `redis` through `docker compose`
2. `up` applies schema with `python -m alembic upgrade head`
3. `up` starts `public`, `input`, `review`, `ingest`, `notification`, `llm`, and `frontend`
4. frontend readiness is checked through `/login`, not `/`, because `/` redirects unauthenticated users
5. `status` reports infra reachability plus per-process health, pid, and log path
6. `down` stops only the app layer
7. `down --infra` additionally stops this repo's compose-managed `postgres` and `redis`
8. logs and pid files are written to `output/dev-stack/`

## Prerequisites

Required before acceptance:

1. root `.env` exists and contains valid app, database, redis, and LLM settings
2. `frontend/node_modules` exists
3. `docker compose` is available
4. local launcher ports are free unless already owned by this stack:
   - `3000`, `8200`, `8201`, `8202`, `8203`, `8204`, `8205`, `5432`, `6379`

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

### 2. Verify runtime reachability

Expected result:

1. `http://127.0.0.1:3000/login` returns `200`
2. unauthenticated `http://127.0.0.1:3000/` redirects to `/login`
3. backend health endpoints return `200`:
   - `http://127.0.0.1:8200/health`
   - `http://127.0.0.1:8201/health`
   - `http://127.0.0.1:8202/health`
   - `http://127.0.0.1:8203/health`
   - `http://127.0.0.1:8204/health`
   - `http://127.0.0.1:8205/health`

### 3. Frontend walkthrough

Minimum UI checks:

1. unauthenticated root/dashboard access redirects to `/login`
2. register creates a user session and lands on `/onboarding` when no source exists
3. `/sources` shows the current user's sources only
4. Sources page accepts only `Canvas ICS URL` for ICS input; no `source_key` or `display_name` field remains
5. saving Canvas ICS creates or updates a single per-user Canvas ICS source
6. Gmail OAuth is visible and usable from `/sources`
7. Overview shows structured source health, not raw backend exception text
8. review pages render loading, empty, and populated states without leaking another user's data
9. Settings keeps `notify_email` read-only
10. logout returns the browser to `/login`
11. mobile navigation opens as a sheet on narrow screens and closes after navigation

### 4. Launcher operability

Validate:

```bash
scripts/dev_stack.sh status
scripts/dev_stack.sh logs frontend
scripts/dev_stack.sh logs input
```

For browser flow checks, use the repo-local Playwright wrapper:

```bash
scripts/run_playwright_cli.sh bootstrap
scripts/run_playwright_cli.sh open http://127.0.0.1:3000/login
scripts/run_playwright_cli.sh snapshot
scripts/run_playwright_cli.sh screenshot
```

Expected result:

1. `status` shows per-service pid, health, and log path
2. `logs <service>` tails the correct log file
3. Playwright wrapper runs without relying on `~/.npm` cache

### 5. Shutdown

Application layer only:

```bash
scripts/dev_stack.sh down
```

Then verify app ports are released:

1. `3000`
2. `8200`
3. `8201`
4. `8202`
5. `8203`
6. `8204`
7. `8205`

Optional infra shutdown:

```bash
scripts/dev_stack.sh down --infra
```

## Acceptance Criteria

The release is accepted when all of the following are true:

1. `scripts/dev_stack.sh up` brings the full local stack to a usable state from a clean shell
2. frontend UI is reachable at `http://127.0.0.1:3000`
3. public-service and internal runtime services return healthy status
4. frontend can proxy successfully through `public-service`
5. `scripts/dev_stack.sh status` reports healthy application state during runtime
6. `/sources` uses the single Canvas ICS link workflow
7. `/` shows source health rather than raw backend error output
8. `scripts/dev_stack.sh down` stops the app layer cleanly
9. `scripts/dev_stack.sh down --infra` stops compose-managed infra cleanly

## Known Limitations

1. this launcher is for local development and acceptance only; it is not a production deployment tool
2. Gmail OAuth depends on working Google app configuration and local secret file setup
3. `down --infra` only stops this repo's `docker compose` services; it does not stop unrelated external local containers or services using the same ports
4. frontend uses polling-based file watching in the launcher to reduce local `EMFILE` watcher failures on this machine
5. some review evidence previews can still return backend `404` if the underlying seeded/test change has no persisted evidence file; the UI should still present a controlled error state
