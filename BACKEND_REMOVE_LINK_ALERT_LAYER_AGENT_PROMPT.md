You are working in the CalendarDIFF repo.

Read these files first, in order:

1. `/Users/lishehao/Desktop/Project/CalendarDIFF/ENTITY_FIRST_SEMANTIC_SPEC.md`
2. `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_AGENT_WORKFLOW.md`
3. `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_REMOVE_LINK_ALERT_LAYER_SPEC.md`

Treat them as the source of truth for this task.

Your job is to implement the backend-only removal of the `EventLinkAlert` layer.

Fixed direction:

- link governance becomes two-lane only: accepted links and candidate review
- `event_link_alerts` and all alert-only side effects are removed
- frontend is out of scope

Requirements:

1. derive your own execution plan from the spec
2. implement the backend changes
3. update this report file in place:
   `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_REMOVE_LINK_ALERT_LAYER_AGENT_REPORT.md`
4. keep frontend untouched

Do not:

- keep dead alert compatibility shims
- invent a replacement alert queue
- broaden scope into frontend work
- stop after analysis

When finished:

- update the report file
- reply in Chinese with a short summary
