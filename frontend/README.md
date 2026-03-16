# Frontend

The frontend talks to the monolith backend only.

## Expected env
- `BACKEND_BASE_URL=http://127.0.0.1:8200`
- `BACKEND_API_KEY=<APP_API_KEY>`

## Checks
```bash
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```
