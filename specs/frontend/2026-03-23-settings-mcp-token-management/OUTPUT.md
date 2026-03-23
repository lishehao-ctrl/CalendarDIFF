# OUTPUT

## Status

- Implemented in frontend

## Files changed

- [frontend/components/settings-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/settings-panel.tsx)
- [frontend/components/settings-mcp-access-card.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/settings-mcp-access-card.tsx)
- [frontend/lib/api/settings.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/api/settings.ts)
- [frontend/lib/types.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/types.ts)
- [frontend/lib/demo-backend.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/demo-backend.ts)
- [frontend/lib/i18n/runtime.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/runtime.ts)
- [frontend/lib/i18n/dictionaries/en.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/dictionaries/en.ts)
- [frontend/lib/i18n/dictionaries/zh-CN.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/dictionaries/zh-CN.ts)

## What shipped

- Added MCP token API helpers:
  - `getMcpTokens()`
  - `createMcpToken(payload)`
  - `revokeMcpToken(tokenId)`
- Added frontend types:
  - `McpAccessToken`
  - `McpAccessTokenCreateResponse`
- Added a new `MCP Access` section inside Settings, below the existing account/timezone card.
- Implemented:
  - create token form
  - expiry selector with `7 / 30 / 90 / 365 days`
  - one-time reveal panel after create
  - copy token action with copied state
  - token list
  - revoke confirmation flow
  - status badges for `Active / Expired / Revoked`
  - small OpenClaw / OpenClaw-derived client usage hint
- Preserved the one-time secret rule:
  - token value is only shown from the create response
  - token secret is never re-read from list rows
- Added preview/demo support for `/preview/settings` by extending the frontend demo backend with MCP token list/create/revoke behavior.
- Updated Settings page framing copy so the lane now matches the expanded product scope:
  - account
  - timezone
  - language
  - MCP access
- Narrowed product language away from `QClaw` so the UI now speaks in terms of `OpenClaw` and `OpenClaw-derived clients`.

## Validation commands run

- `npm run typecheck`
- `npm run lint`
- `NEXT_DIST_DIR=.next-prod npm run build`

## Validation result

- All passed

## Notes on intentionally unresolved UX gaps

- Revoke confirmation is implemented as an inline confirmation state inside the token row, not a separate modal dialog component.
  - This keeps the change inside the current frontend architecture without introducing a new alert-dialog primitive.
- Scope display is a simple joined summary of backend-returned `scopes`.
  - The UI does not invent friendlier scope labels because the backend contract does not provide them.
- Token creation uses a client-side copy action only.
  - There is no “download config” or “show again later” flow, by design.
