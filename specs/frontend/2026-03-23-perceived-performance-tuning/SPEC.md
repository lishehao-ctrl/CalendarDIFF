# Perceived Performance Tuning

## Summary

Improve perceived frontend speed without changing backend semantics or introducing a new state-management architecture.

This pass is about:

- reducing route-switch waiting
- reducing heavy first-paint cost on lane pages
- replacing whole-page loading with local loading where possible
- keeping current visual/product behavior intact

This is not a rewrite.
It is a surgical pass.

## Goal

The user should feel:

- sidebar navigation responds faster
- `Settings`, `Families`, and heavy detail surfaces appear sooner
- a polling update or detail fetch does not make the whole page feel like it refreshed

## Constraints

- Do not redesign page hierarchy.
- Do not invent a new data layer.
- Reuse existing:
  - `useApiResource`
  - `resource-cache`
  - `workspace-preload`
- Do not add a new global store.
- Do not change backend API contracts.
- Prefer local dynamic imports and suspense fallbacks over broad architectural churn.

## Existing Good Infrastructure To Reuse

Already present:

- `frontend/lib/resource-cache.ts`
- `frontend/lib/use-api-resource.ts`
- `frontend/lib/workspace-preload.ts`
- route prefetch in `app-shell.tsx`

So this pass should build on top of those, not replace them.

## Primary Targets

## 1. Settings heavy secondary surfaces

### Target

- `SettingsMcpAccessCard`

### Why

- it is not needed for first paint of the settings shell
- it contains heavier UI state, list rendering, create/revoke flows

### Requirement

- keep account/timezone section visible immediately
- dynamically import the MCP access card
- use a small card-level loading placeholder while it loads

## 2. Families heavy governance panel

### Target

- `family-management-panel`

### Why

- families is one of the heaviest governance surfaces
- full editor/detail controls do not need to block shell render

### Requirement

- keep the route shell and primary intro visible immediately
- dynamically import the heavy panel
- use a lane-local loading placeholder

## 3. Manual heavy fallback panel

### Target

- `manual-workbench-panel`

### Requirement

- dynamically import the main panel
- route shell should appear before heavy form/editor logic

## 4. Source detail secondary sections

### Target

- `source-observability-sections`

### Requirement

- keep top source identity/status visible quickly
- defer the deeper observability sections if needed
- when observability refreshes, only that section should load, not the whole page shell

## 5. Connect/setup panels

### Target

- `gmail-source-setup-panel`
- `canvas-ics-setup-panel`

### Requirement

- route shell first
- heavy setup body dynamic-imported if it improves initial route responsiveness

## Route-Level Guidance

## Good candidates for `next/dynamic`

- `SettingsMcpAccessCard`
- `FamilyManagementPanel`
- `ManualWorkbenchPanel`
- `SourceObservabilitySections`
- setup/connect panels
- heavy legal page wrappers if useful

## Bad candidates for aggressive dynamic splitting

- `AppShell`
- sidebar
- overview hero
- changes inbox shell
- sources list shell

These must stay responsive and stable.

## Local Loading Rules

### Do

- use card-level or panel-level loading states
- keep shell/header/intro visible
- keep already loaded data on screen during background refresh
- isolate loading indicators to the panel that is actually fetching

### Do not

- blank the whole page because one section is refreshing
- replace the whole route with a spinner if only one secondary widget is loading

## Settings-Specific Rule

When `SettingsMcpAccessCard` fetches:

- the account/timezone card must remain interactive
- only the MCP card may show a loading state

## Sources-Specific Rule

When source observability changes:

- source identity card should remain visible
- only the observability/detail section should update
- do not visually simulate a full page reload

## Changes-Specific Rule

For changes detail / edit / evidence:

- inbox list should stay stable
- detail-side fetches should not blank the whole route

This pass does not require a redesign of the changes workflow.
It only reduces perceived latency.

## Suggested Implementation Approach

## A. Dynamic imports

Use `next/dynamic` for heavy secondary panels.

Pattern:

- route/page renders shell immediately
- heavy panel loads dynamically
- panel fallback is a compact local placeholder, not a full-page spinner

## B. Preserve existing cache usage

Do not replace:

- `useApiResource`
- `preloadWorkspaceLane`

Instead:

- make sure `Settings` preloads both profile and MCP token list if useful
- make sure heavy pages still reuse cached lane data after route switch

## C. Keep refresh local

If a component already owns its own fetch lifecycle, keep the loading state inside that component.

## Specific Expected Work

### `frontend/app/(app)/settings/page.tsx`
- keep route shell light
- defer MCP section if necessary

### `frontend/components/settings-panel.tsx`
- isolate MCP section loading from account section

### `frontend/components/settings-mcp-access-card.tsx`
- safe to be the main dynamic-loaded unit

### `frontend/app/(app)/families/page.tsx`
- make heavy panel dynamic if route currently blocks

### `frontend/app/(app)/manual/page.tsx`
- make heavy panel dynamic if route currently blocks

### `frontend/app/(app)/sources/[sourceId]/page.tsx`
- keep top summary immediate
- observability/details can be deferred

### `frontend/components/source-observability-sections.tsx`
- local refresh only

## Validation

Required:

```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```

Manual smoke:

1. open app shell
2. switch between `Overview`, `Sources`, `Changes`, `Settings`
3. confirm shell appears immediately
4. open `Settings`
5. confirm account card renders before MCP card finishes loading
6. open `Families`
7. confirm route shell renders before heavy governance panel
8. open one source detail
9. confirm source header stays visible while deeper sections refresh

## Non-goals

- no virtualization pass
- no global store rewrite
- no backend batching change in this spec
- no speculative API redesign
- no visual redesign
