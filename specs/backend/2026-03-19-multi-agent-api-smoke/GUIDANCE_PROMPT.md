Use the existing CalendarDIFF public API and replay/acceptance scripts to run a multi-agent smoke test against the year-scale datasets.

Goal:

- run an API-only chronological smoke test
- use the real yearly backbone and noisy inbox simulation
- keep all actions on public routes only
- report stability, operator burden, and semantic drift clearly

Dataset choice is fixed:

- ICS backbone: `year_timeline`
- Gmail inbox stream: `year_timeline_full_sim`

Do not use `year_timeline_mixed` as the primary smoke source.
It is regression material, not the main chronological user-environment dataset.

Role split:

1. Driver
   - start or continue the replay/acceptance run
   - inspect checkpoints
   - summarize current system posture
   - tell other agents what to act on

2. Changes Operator
   - handle pending changes through `/changes*`
   - prefer approve / reject / edit-then-approve
   - explain why the decision is safe

3. Families Operator
   - handle family governance through `/families*`
   - rename, create, relink, and raw-type suggestion decisions

4. Sources + Manual Auditor
   - inspect `/sources*` and `/sync-requests/{id}`
   - decide whether runtime is trustworthy enough to continue
   - use `/manual/events*` only when fallback is necessary

Execution rules:

- use public API only
- do not modify DB
- do not use internal services
- do not edit fixtures
- treat `Changes` as the primary lane
- treat `Manual` as fallback only

Checkpoint protocol:

- Driver must provide:
  - checkpoint index
  - current batch / time label
  - pending changes summary
  - source posture summary
  - family suggestion summary
  - manual fallback summary

Priority order:

1. Changes
2. Sources
3. Families
4. Manual

Recommended smoke order:

1. Fast smoke: 2-4 checkpoints with reduced window
2. Monthly smoke: one month or one quarter
3. Full-year smoke: full `year_timeline + year_timeline_full_sim`

Success criteria:

- bootstrap completes naturally
- replay continues without DB intervention
- Gmail/ICS remain interpretable together
- Changes is still the main operator workload
- Families is governance, not inbox
- Manual remains limited fallback
- source observability is good enough for pause/continue decisions

When reporting, always separate:

- runtime stability
- semantic stability
- operator burden
- source trust / observability
- dataset realism observations
