Read this first:
- /Users/lishehao/Desktop/Project/CalendarDIFF/specs/frontend/2026-03-23-settings-mcp-token-management/SPEC.md

Implement the Settings MCP token management surface exactly within the current frontend architecture.

Scope:
- `frontend/components/settings-panel.tsx`
- optionally add `frontend/components/settings-mcp-access-card.tsx`
- `frontend/lib/api/settings.ts`
- `frontend/lib/types.ts`
- `frontend/lib/i18n/dictionaries/en.ts`
- `frontend/lib/i18n/dictionaries/zh-CN.ts`

Rules:
- do not change backend semantics
- do not fabricate fields the backend does not return
- do not re-show token secrets after initial creation
- keep the MCP area inside Settings, not a new lane
- preserve current visual language and spacing patterns
- use existing loading/error/empty patterns

Must-have UX:
- create token
- one-time reveal panel with copy
- token list
- revoke flow with confirmation
- small usage hint for QClaw/OpenClaw

API contract to use:
- `GET /settings/mcp-tokens`
- `POST /settings/mcp-tokens`
- `DELETE /settings/mcp-tokens/{token_id}`

Important:
- `token` only exists in the create response
- after page refresh it must disappear from the UI
- revoked tokens stay listed but cannot be used

When done, update:
- `/Users/lishehao/Desktop/Project/CalendarDIFF/specs/frontend/2026-03-23-settings-mcp-token-management/OUTPUT.md`

Include in OUTPUT:
- files changed
- validation commands run
- notes on any UX gaps left intentionally unresolved
