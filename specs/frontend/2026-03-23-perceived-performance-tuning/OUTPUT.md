# OUTPUT

## Status

- Implemented in frontend

## Files changed

- [frontend/components/panel-loading-placeholder.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/panel-loading-placeholder.tsx)
- [frontend/components/settings-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/settings-panel.tsx)
- [frontend/components/family-management-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/family-management-panel.tsx)
- [frontend/components/manual-workbench-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/manual-workbench-panel.tsx)
- [frontend/components/source-detail-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/source-detail-panel.tsx)
- [frontend/components/gmail-source-setup-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/gmail-source-setup-panel.tsx)
- [frontend/components/canvas-ics-setup-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/canvas-ics-setup-panel.tsx)
- [frontend/app/(app)/families/page.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/app/(app)/families/page.tsx)
- [frontend/app/(public)/preview/families/page.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/app/(public)/preview/families/page.tsx)
- [frontend/app/(app)/manual/page.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/app/(app)/manual/page.tsx)
- [frontend/app/(public)/preview/manual/page.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/app/(public)/preview/manual/page.tsx)
- [frontend/app/(app)/sources/connect/gmail/page.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/app/(app)/sources/connect/gmail/page.tsx)
- [frontend/app/(public)/preview/sources/connect/gmail/page.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/app/(public)/preview/sources/connect/gmail/page.tsx)
- [frontend/app/(app)/sources/connect/canvas-ics/page.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/app/(app)/sources/connect/canvas-ics/page.tsx)
- [frontend/app/(public)/preview/sources/connect/canvas-ics/page.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/app/(public)/preview/sources/connect/canvas-ics/page.tsx)
- [frontend/lib/api/families.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/api/families.ts)
- [frontend/lib/api/manual.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/api/manual.ts)
- [frontend/lib/workspace-preload.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/workspace-preload.ts)

## Dynamic import decisions

- `SettingsMcpAccessCard`
  - deferred inside [settings-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/settings-panel.tsx)
  - account/timezone section remains immediate
- `FamilyManagementPanel`
  - deferred at the route level in both app and preview pages
  - fallback keeps a lightweight lane-local shell visible
- `ManualWorkbenchPanel`
  - deferred at the route level in both app and preview pages
  - page intro stays visible immediately
- `GmailSourceSetupPanel`
  - deferred at the route level in app and preview pages
  - localized page header remains immediate
- `CanvasIcsSetupPanel`
  - deferred at the route level in app and preview pages
  - localized page header remains immediate
- `SourceObservabilitySections`
  - deferred inside the Gmail and Canvas setup panels
  - source connect shell stays visible while the deeper observability block loads

## What loading became local

- `Settings`
  - MCP access loading is now isolated to the MCP card
  - account/timezone card remains visible and interactive
- `Families`
  - route now shows a lane-local placeholder instead of blocking the full route on the heavy panel bundle
  - family data also now uses cache keys so route switches can reuse preloaded snapshots
- `Manual`
  - route intro renders before the heavy workbench bundle
  - family/manual datasets now use cache keys so transitions can reuse lane data
- `Source detail`
  - the top source identity / action shell no longer waits on observability + history together
  - observability and replay history now load independently inside their own cards
  - background refreshes no longer blank the whole detail route
- `Connect/setup panels`
  - page header renders before the heavy setup body
  - deeper observability block inside setup is lazy-loaded separately

## Cache / preload additions

- Added cache keys for:
  - families list
  - families status
  - families courses
  - families raw types
  - families suggestions
  - manual events
- Extended [workspace-preload.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/workspace-preload.ts):
  - `Settings` now preloads MCP token list in addition to profile
  - `Families` lane now preloads its primary governance datasets
  - `Manual` lane now preloads family + manual event datasets
  - `Sources` lane now also preloads `status=all` to help source detail and connect/setup pages

## Validation commands run

- `npm run typecheck`
- `npm run lint`
- `NEXT_DIST_DIR=.next-prod npm run build`

## Validation result

- All passed

## Smoke notes

- Playwright smoke confirmed these routes still open successfully:
  - `/preview/settings`
  - `/preview/families`
  - `/preview/sources/1`
- Source detail top shell remained visible while deeper cards loaded.
- Settings and Families preview routes remained reachable after the dynamic-splitting pass.

## Intentionally unresolved

- `FamilyManagementPanel` still owns its full hero/search/tab shell inside the heavy component.
  - This pass only defers the panel bundle and prewarms its data; it does not split the family hero into a separate server shell.
- No new performance metrics or fake latency indicators were added.
  - This pass only improves perceived responsiveness through code-splitting, caching, and local loading boundaries.
