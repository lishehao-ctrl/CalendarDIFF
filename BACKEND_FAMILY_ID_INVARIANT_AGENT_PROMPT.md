You are working in the CalendarDIFF repo.

Read these files first, in order:

1. `/Users/lishehao/Desktop/Project/CalendarDIFF/ENTITY_FIRST_SEMANTIC_SPEC.md`
2. `/Users/lishehao/Desktop/Project/CalendarDIFF/DATA_FLOW_HARDENING_SPEC.md`
3. `/Users/lishehao/Desktop/Project/CalendarDIFF/FAMILY_LABEL_AUTHORITY_SPEC.md`
4. `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_FAMILY_ID_INVARIANT_SPEC.md`
5. `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_AGENT_WORKFLOW.md`

Treat them as the source of truth for this task.

Your job is to harden the backend so missing `family_id` is no longer a normal review-flow state.

Important fixed rules:

- every normal reviewable event must have `family_id`
- default fallback is `raw type -> own family`
- if course identity is missing, the record must go to a backend unresolved ingest bucket
- unresolved ingest records must not produce `changes`
- unresolved ingest records must not emit `review.pending.created`
- frontend is out of scope for this pass

Execution requirements:

1. derive your own detailed execution plan from the spec
2. implement the backend changes
3. write your report into:
   `/Users/lishehao/Desktop/Project/CalendarDIFF/BACKEND_FAMILY_ID_INVARIANT_AGENT_REPORT.md`
4. keep the report updated with what you changed and what you validated

Do not:

- change frontend files
- reintroduce permissive “family_id can be null in normal flow” logic
- hide unresolved records inside normal `changes`
- stop after analysis

Recommended implementation order:

1. unresolved ingest bucket model + persistence path
2. family-resolution hard invariant in apply paths
3. proposal/outbox isolation for unresolved records
4. recovery/supersede behavior for later valid ingest
5. backend tests
6. backend docs if needed

When you finish, update the report file and also reply in Chinese with a short summary.
