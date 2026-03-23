# Settings MCP Access Smoke

Date:
- 2026-03-23

Scope:
- frontend/backend integration smoke for `Settings -> MCP Access`
- local web flow validation
- public MCP endpoint sanity check

## Local Environment

- frontend: `http://127.0.0.1:3000`
- backend: `http://127.0.0.1:8200`
- database: local PostgreSQL
- runtime workers: disabled for smoke

## Local Flow Verified

Validated with Playwright against the real local frontend and backend.

Steps completed:

1. log in to local account
2. open `Settings`
3. verify `MCP Access` section renders
4. create a token
5. verify one-time reveal panel appears
6. click `Copy token`
7. verify copy-state UI changes to `Copied`
8. refresh page
9. verify secret is no longer shown
10. verify token row still appears in token list
11. revoke token
12. verify token row status becomes `Revoked`
13. verify backend `/settings/mcp-tokens` returns the same token with `revoked_at`

## Local Result

Passed:

- create token path is wired end-to-end
- one-time reveal behavior works
- refresh removes token secret from UI
- revoke path updates both UI and backend state

## Public MCP Verification

Verified:

- `https://cal.shehao.app/mcp` is reachable
- unauthenticated request returns `401`
- authenticated request no longer returns `401`
- authenticated request reaches MCP protocol layer and responds with protocol-level `406` when the client does not request the correct content type

Interpretation:

- public MCP auth and routing are live
- the endpoint is no longer falling through to the frontend app

## Notes

- local login smoke used an already-existing local account after completing onboarding prerequisites through backend calls
- this smoke focused only on MCP token management; it did not re-audit unrelated Settings functionality
