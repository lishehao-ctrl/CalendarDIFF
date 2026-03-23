Read this first:
- /Users/lishehao/Desktop/Project/CalendarDIFF/specs/frontend/2026-03-23-agent-entry-surfaces/SPEC.md

Implement frontend agent entry surfaces inside:

- Overview
- Changes
- Sources

Do not add a new top-level Agent lane.

Use backend agent APIs already available:

- `GET /agent/context/workspace`
- `GET /agent/context/changes/{change_id}`
- `GET /agent/context/sources/{source_id}`
- `POST /agent/proposals/change-decision`
- `POST /agent/proposals/source-recovery`
- `GET /agent/proposals/{proposal_id}`
- `POST /agent/approval-tickets`
- `GET /agent/approval-tickets/{ticket_id}`
- `POST /agent/approval-tickets/{ticket_id}/confirm`
- `POST /agent/approval-tickets/{ticket_id}/cancel`

Rules:

- agent is a copilot layer, not a new lane
- do not auto-run proposals on page load
- do not fake execution for non-executable proposals
- do not add agent execution to Families or Manual
- keep loading local to the agent card

Priority:

1. Overview `Agent Brief`
2. Changes `Agent Suggestion`
3. Sources `Recovery Assistant`

Add frontend API helpers and types as needed.

Keep UI language product-facing:
- `Agent brief`
- `Suggestion`
- `Ready to confirm`
- `Needs web review`

Avoid exposing raw backend field names.

When done, update:
- `/Users/lishehao/Desktop/Project/CalendarDIFF/specs/frontend/2026-03-23-agent-entry-surfaces/OUTPUT.md`

Include:
- files changed
- how each lane entry point was added
- which proposal/ticket states are rendered
- validation commands run
