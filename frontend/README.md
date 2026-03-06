# CalendarDIFF Frontend

## Local env

Create `frontend/.env.local` from the example:

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

## Proxy routing

The browser never talks directly to the Python services. All requests go through `app/api/backend/[...path]/route.ts`.

- `/review/*` routes to `REVIEW_BACKEND_BASE_URL`
- everything else in the current MVP routes to `INPUT_BACKEND_BASE_URL`
- both can fall back to `BACKEND_BASE_URL` if you run a unified gateway

## Commands

```bash
npm install
npm run dev
npm run typecheck
npm run lint
npm run build
```
