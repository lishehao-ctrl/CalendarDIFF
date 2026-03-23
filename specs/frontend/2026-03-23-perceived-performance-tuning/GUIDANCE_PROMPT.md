Read this first:
- /Users/lishehao/Desktop/Project/CalendarDIFF/specs/frontend/2026-03-23-perceived-performance-tuning/SPEC.md

Implement a narrow perceived-performance pass for the current frontend.

Main rule:
- improve perceived speed without changing backend contracts or rewriting app state management

Build on existing infrastructure:
- `useApiResource`
- `resource-cache`
- `workspace-preload`

Focus on:
- dynamic-importing heavy secondary panels
- keeping route shells visible immediately
- limiting loading indicators to the panel actually fetching

Good targets:
- `SettingsMcpAccessCard`
- `FamilyManagementPanel`
- `ManualWorkbenchPanel`
- `SourceObservabilitySections`
- source connect/setup panels if helpful

Do not:
- dynamic-import the whole app shell
- blank pages during section refresh
- introduce a new global store
- redesign product behavior

Validation required:

```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```

Also do a local manual/Playwright smoke if possible for:
- sidebar route switches
- `Settings`
- `Families`
- source detail

When done, update:
- `/Users/lishehao/Desktop/Project/CalendarDIFF/specs/frontend/2026-03-23-perceived-performance-tuning/OUTPUT.md`

Include:
- files changed
- dynamic import decisions made
- what loading became local instead of page-wide
- validation commands run
