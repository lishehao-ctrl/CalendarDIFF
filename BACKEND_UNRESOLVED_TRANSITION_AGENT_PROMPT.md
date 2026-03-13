You are working in the CalendarDIFF repo.

Read these files first, in order:

1. `/Users/lishehao/Desktop/Project/CalendarDIFF/ENTITY_FIRST_SEMANTIC_SPEC.md`
2. `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_AGENT_WORKFLOW.md`
3. `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_FAMILY_ID_INVARIANT_SPEC.md`
4. `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_UNRESOLVED_TRANSITION_SPEC.md`

Treat them as the source of truth for this task.

Your job is to implement the backend-only unresolved-transition hardening pass described in the spec.

Fixed direction:

- unresolved is an ingest-only isolation state
- `valid -> unresolved` must retire the prior active observation for that source record
- `valid -> unresolved` must not create a new semantic proposal or `review.pending.created`
- frontend is out of scope

Execution requirements:

1. derive your own detailed execution plan from the spec
2. implement the backend changes
3. update this report file in place:
   `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_UNRESOLVED_TRANSITION_AGENT_REPORT.md`
4. keep frontend untouched

Do not:

- reintroduce permissive normal-flow handling for unresolved records
- leave stale active observations behind for unresolved source records
- turn parser uncertainty into synthetic semantic removals
- stop after analysis

Recommended order:

1. inspect calendar and Gmail unresolved transition handling
2. add or extract shared observation-retirement logic if helpful
3. enforce `valid -> unresolved` retirement without semantic side effects
4. add regression coverage for calendar and Gmail transition cases
5. run targeted backend validation
6. update backend docs only if runtime wording changed materially

When you finish:

- update the report file
- reply in Chinese with a short summary

Keep the diff narrowly focused on this transition bug and its regression coverage.
