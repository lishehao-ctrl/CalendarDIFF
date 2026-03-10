# CalendarDIFF Frontend

## Runtime Model

The frontend is a Next.js app-router console for the authenticated CalendarDIFF dashboard.

Current user flow:

1. `/login`
2. `/register`
3. `/onboarding`
4. `/`
5. `/sources`
6. `/review/changes`
7. `/review/links`
8. `/settings`

Current source model:

1. one Canvas ICS link per user
2. one Gmail OAuth source per user
3. browser requests always proxy through `app/api/backend/[...path]/route.ts` to the unified public API

## Local Env

Create `frontend/.env.local` from the example only if you are running the frontend manually.

```bash
cp .env.local.example .env.local
```

Required for the current multi-service backend:

- `BACKEND_BASE_URL`
- `BACKEND_API_KEY`

## Preferred Startup

Use the repo launcher for the active local stack:

```bash
scripts/dev_stack.sh up
```

For a fully containerized app, run from the repo root:

```bash
docker compose up --build
```

Manual frontend-only startup is still available if backend services are already running.

## Proxy Routing

The browser never talks directly to the Python services. All requests go through `app/api/backend/[...path]/route.ts`, which proxies to the unified public API defined by `BACKEND_BASE_URL`.

## Commands

```bash
npm install
NEXT_DIST_DIR=.next-dev npm run dev
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```
