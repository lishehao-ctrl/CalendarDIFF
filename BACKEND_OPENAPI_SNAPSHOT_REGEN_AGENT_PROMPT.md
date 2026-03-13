You are working in the CalendarDIFF repo.

Read these files first, in order:

1. `/Users/lishehao/Desktop/Project/CalendarDIFF/ENTITY_FIRST_SEMANTIC_SPEC.md`
2. `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_AGENT_WORKFLOW.md`
3. `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_REMOVE_LINK_ALERT_LAYER_SPEC.md`
4. `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_OPENAPI_SNAPSHOT_REGEN_SPEC.md`

Treat them as the source of truth for this task.

Your job is to finish the backend-only OpenAPI contract sync after the EventLinkAlert removal.

Fixed direction:

- the alert layer remains removed
- snapshots must be regenerated to match current runtime
- do not restore deleted alert APIs
- frontend is out of scope

Requirements:

1. derive your own execution plan from the spec
2. implement the backend-only snapshot sync
3. update this report file in place:
   `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_OPENAPI_SNAPSHOT_REGEN_AGENT_REPORT.md`
4. keep frontend untouched

Do not:

- hand-wave the failing snapshot test without fixing the checked-in artifacts
- reintroduce removed alert-layer routes or fields
- broaden scope into new backend refactors
- stop after analysis

When finished:

- update the report file
- reply in Chinese with a short summary
