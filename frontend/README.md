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
3. browser requests always proxy through `app/api/backend/[...path]/route.ts`

## Local Env

Create `frontend/.env.local` from the example only if you are running the frontend manually.

```bash
cp .env.local.example .env.local
```

Required for the current multi-service backend:

- `INPUT_BACKEND_BASE_URL`
- `REVIEW_BACKEND_BASE_URL`
- `BACKEND_API_KEY`

Optional:

- `BACKEND_BASE_URL`
  Use this only if you expose a single gateway in front of the backend. If set, it becomes the fallback for both input and review requests.

## Preferred Startup

Use the repo launcher for the active local stack:

```bash
scripts/dev_stack.sh up
```

Manual frontend-only startup is still available if backend services are already running.

## Proxy Routing

The browser never talks directly to the Python services. All requests go through `app/api/backend/[...path]/route.ts`.

- `/review/*` routes to `REVIEW_BACKEND_BASE_URL`
- everything else routes to `INPUT_BACKEND_BASE_URL`
- both can fall back to `BACKEND_BASE_URL` if you run a unified gateway

## Commands

```bash
npm install
npm run dev
npm run typecheck
npm run lint
npm run build
```
