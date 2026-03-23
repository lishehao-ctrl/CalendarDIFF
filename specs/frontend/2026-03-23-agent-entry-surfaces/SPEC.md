# Agent Entry Surfaces

## Summary

Expose the new backend agent layer inside the existing product lanes.

Do not add a new top-level `Agent` lane yet.

This pass should introduce embedded agent entry points in:

- `Overview`
- `Changes`
- `Sources`

The backend already exposes:

- agent context
- proposals
- approval tickets

The frontend goal is to make those capabilities reachable in a way that matches existing user mental models.

## Product Principle

The agent is not a separate product lane yet.
It is a copilot layer on top of the current lanes.

Therefore:

- `Overview` gets a workspace-level agent brief
- `Changes` gets a change-level agent suggestion
- `Sources` gets a source recovery assistant

Do not add:

- new sidebar item
- new standalone `/agent` route
- families/manual execution entry points

## Backend Contract

### Context

- `GET /agent/context/workspace`
- `GET /agent/context/changes/{change_id}`
- `GET /agent/context/sources/{source_id}`

### Proposal

- `POST /agent/proposals/change-decision`
- `POST /agent/proposals/source-recovery`
- `GET /agent/proposals/{proposal_id}`

### Approval

- `POST /agent/approval-tickets`
- `GET /agent/approval-tickets/{ticket_id}`
- `POST /agent/approval-tickets/{ticket_id}/confirm`
- `POST /agent/approval-tickets/{ticket_id}/cancel`

## Scope

## 1. Overview agent brief

Add a compact card in `Overview`.

Purpose:

- answer “what should I do next?”

Source:

- `GET /agent/context/workspace`

Display:

- recommended next action
- lane
- reason
- risk level
- blocking conditions
- top 1-3 pending changes
- quick CTA to open the recommended lane

Suggested title:
- `Agent Brief`

Suggested actions:
- `Open recommended lane`
- `Open top change`
- `Open Sources` if blockers are source-related

This is read-only in v1.
Do not create proposals from Overview yet.

## 2. Change-level agent suggestion

Add an embedded agent card inside the `Changes` detail workspace.

Purpose:

- explain the current change
- optionally create a structured suggestion
- optionally create/confirm a low-risk approval ticket

Source:

- `GET /agent/context/changes/{change_id}`

Actions:

- `Get suggestion`
  - calls `POST /agent/proposals/change-decision`
- if proposal is executable:
  - `Create approval ticket`
  - `Confirm now`
- if proposal is not executable:
  - show web-only explanation
  - do not render misleading execution buttons

Display:

- suggested action
- reason
- risk level
- blocking conditions
- available next tools

Important:

- do not auto-create proposals on page load
- keep proposal creation user-triggered

## 3. Source recovery assistant

Add an embedded agent card inside `SourceDetailPanel`.

Purpose:

- explain source posture
- suggest recovery
- allow low-risk sync execution through approval tickets

Source:

- `GET /agent/context/sources/{source_id}`

Actions:

- `Suggest recovery`
  - calls `POST /agent/proposals/source-recovery`
- if proposal payload is executable:
  - `Create approval ticket`
  - `Confirm now`
- if proposal is not executable:
  - render `Open connection flow`
  - explain why it stays web-only

Important:

- only `run_source_sync` should be treated as executable in this pass
- `reconnect_gmail` and similar actions remain guidance-only

## UI State Model

Each embedded agent surface should support these states:

### A. Context loading

- local skeleton / lightweight card placeholder
- do not blank the rest of the lane

### B. Context ready

- show summary/reason/risk
- show primary action button

### C. Proposal loading

- disable proposal CTA
- keep context visible

### D. Proposal ready

- show proposal summary
- show executable or web-only branch

### E. Ticket creating

- disable ticket CTA

### F. Ticket ready

- show ticket status and confirm/cancel actions

### G. Ticket executed / canceled / failed

- keep result visible
- show final state
- allow refresh/reload of context

## Suggested Component Structure

### Overview

- `AgentBriefCard`

### Changes

- `ChangeAgentCard`
- `AgentProposalCard`
- `ApprovalTicketActionBar`

### Sources

- `SourceRecoveryAgentCard`
- `AgentProposalCard`
- `ApprovalTicketActionBar`

Common:

- `agent-entry-card.tsx`
- `agent-proposal-card.tsx`
- `approval-ticket-bar.tsx`

These can be introduced under `frontend/components/`.

## API Client Work

Add API helpers:

### `frontend/lib/api/agents.ts`

- `getAgentWorkspaceContext()`
- `getAgentChangeContext(changeId)`
- `getAgentSourceContext(sourceId)`
- `createChangeDecisionProposal(changeId)`
- `createSourceRecoveryProposal(sourceId)`
- `getAgentProposal(proposalId)`
- `createApprovalTicket(proposalId, channel?)`
- `getApprovalTicket(ticketId)`
- `confirmApprovalTicket(ticketId)`
- `cancelApprovalTicket(ticketId)`

## Types

Add frontend types for:

- workspace context
- change context
- source context
- agent proposal
- approval ticket

Use the backend schema as-is.
Do not “simplify” by throwing away risk or blocking metadata.

## Copy Rules

Use product-facing language.

Avoid:

- `invoke agent`
- `run model`
- `proposal_type`
- `payload_json`
- `approval_ticket`

Prefer:

- `Agent brief`
- `Suggestion`
- `Recommended next step`
- `Ready to confirm`
- `Needs web review`
- `Not safe to run here`

## Important Guardrails

- No new sidebar nav item
- No fake execution for non-executable proposals
- No automatic approval ticket creation on load
- No hidden mutation when the user only asked for a suggestion
- No agent write path in `Families` or `Manual` yet

## Non-goals

- no chat transcript UI
- no freeform ask-anything agent prompt box
- no families/manual agent execution
- no MCP token UX changes in this pass
- no new backend work

## Validation

Frontend:

```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```

Manual smoke:

1. open `Overview`
2. confirm agent brief renders
3. open one change
4. fetch a suggestion
5. if executable, create a ticket
6. confirm/cancel ticket
7. open one source detail
8. fetch recovery suggestion
9. if executable, create and confirm ticket

## Release Standard

The pass is successful if:

- agent entry points exist in `Overview`, `Changes`, and `Sources`
- they remain subordinate to those lanes
- executable actions only appear when the backend says they are executable
- the rest of the page remains stable while agent panels load
