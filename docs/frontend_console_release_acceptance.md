# Frontend Release Acceptance

## Preconditions
- Backend running at `http://127.0.0.1:8200`
- Frontend running at `http://127.0.0.1:3000`
- Valid `APP_API_KEY` configured for the frontend bridge

## Acceptance checklist
- Login/register/session flows work against `/auth/*`
- Settings page reads and writes `/profile/me`
- Sources pages use `/sources/*` and `/onboarding/*`
- Review pages use `/review/changes*` and `/review/links*`
- Family management uses `/review/course-work-item-families*`
- Manual workbench uses `/events/manual*`
- No frontend flow depends on `/users/...`

## Required frontend checks
```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```
