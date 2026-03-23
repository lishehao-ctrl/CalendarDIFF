# OUTPUT

## Status

- Implemented in frontend

## Files changed

- [frontend/lib/api/agents.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/api/agents.ts)
- [frontend/lib/types.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/types.ts)
- [frontend/lib/workspace-preload.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/workspace-preload.ts)
- [frontend/lib/demo-backend.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/demo-backend.ts)
- [frontend/components/agent-brief-card.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/agent-brief-card.tsx)
- [frontend/components/agent-proposal-card.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/agent-proposal-card.tsx)
- [frontend/components/approval-ticket-bar.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/approval-ticket-bar.tsx)
- [frontend/components/change-agent-card.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/change-agent-card.tsx)
- [frontend/components/source-recovery-agent-card.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/source-recovery-agent-card.tsx)
- [frontend/components/overview-page-client.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/overview-page-client.tsx)
- [frontend/components/review-changes-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/review-changes-panel.tsx)
- [frontend/components/source-detail-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/source-detail-panel.tsx)
- [frontend/lib/i18n/dictionaries/en.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/dictionaries/en.ts)
- [frontend/lib/i18n/dictionaries/zh-CN.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/dictionaries/zh-CN.ts)

## How each lane entry point was added

- `Overview`
  - added [AgentBriefCard](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/agent-brief-card.tsx)
  - reads `GET /agent/context/workspace`
  - shows:
    - recommended lane
    - reason
    - risk
    - blocking conditions
    - top pending changes
  - remains read-only in this pass

- `Changes`
  - added [ChangeAgentCard](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/change-agent-card.tsx) inside the decision workspace
  - reads `GET /agent/context/changes/{change_id}`
  - user-triggered suggestion creation via `POST /agent/proposals/change-decision`
  - executable proposals can create approval tickets
  - web-only proposals keep execution buttons hidden and show guidance-only flow

- `Sources`
  - added [SourceRecoveryAgentCard](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/source-recovery-agent-card.tsx) inside [SourceDetailPanel](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/source-detail-panel.tsx)
  - reads `GET /agent/context/sources/{source_id}`
  - user-triggered recovery suggestion via `POST /agent/proposals/source-recovery`
  - only `run_source_sync` is treated as executable
  - reconnect / update settings stay web-only and link back to existing source flows

## Proposal and ticket states rendered

- Context loading
  - local card-level skeleton / loading card only
- Context ready
  - reason, risk, blockers, available tools, primary CTA
- Proposal loading
  - suggestion button disabled while request is in flight
- Proposal ready
  - renders summary, reason, risk, and executable vs web-only branch
- Ticket creating
  - create-ticket CTA disabled
- Ticket ready
  - renders [ApprovalTicketBar](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/approval-ticket-bar.tsx)
  - supports confirm / cancel / refresh status
- Ticket executed / canceled / failed / expired
  - final state stays visible inside the lane card

## Preview/demo support

- extended [demo-backend.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/demo-backend.ts) with:
  - workspace / change / source agent context
  - proposal creation
  - approval ticket creation
  - confirm / cancel flows
- preview keeps agent embedded inside existing lanes; no standalone agent lane was introduced

## Validation commands run

- `npm run typecheck`
- `npm run lint`
- `NEXT_DIST_DIR=.next-prod npm run build`

## Validation result

- All passed

## Notes

- `Overview` top-change CTA uses the existing `Changes` lane by linking to `/changes?focus={changeId}`.
  - [ChangeItemsPanel](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/review-changes-panel.tsx) now reads that query on the client and selects the requested row when present.
- No proposal is auto-created on load.
- No top-level `Agent` lane, `/agent` route, or sidebar item was added.
- Families / Manual remain out of execution scope in this pass.
- Playwright MCP smoke could not complete because the browser bridge kept returning `ERR_CONNECTION_REFUSED` against local `127.0.0.1:3000`, even after the local dev server was started. The implementation was still validated by `typecheck`, `lint`, and `build`.
