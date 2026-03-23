# Frontend Release Acceptance

## Preconditions
- Backend running at `http://127.0.0.1:8200`
- Frontend running at `http://127.0.0.1:3000`
- Valid `APP_API_KEY` configured for the frontend bridge

## Acceptance checklist
- Login/register/session flows work against `/auth/*`
- Settings page uses `/settings`
- Sources pages use `/sources/*` and `/onboarding/*`
- Changes pages use `/changes*`
- Family pages use `/families*`
- Manual workbench uses `/manual*`
- No frontend flow depends on `/users/...`
- Product-shape guidance stays aligned with `docs/frontend_product_shape.md`

## Required frontend checks
```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```
