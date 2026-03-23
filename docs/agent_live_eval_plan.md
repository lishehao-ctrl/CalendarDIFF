# Agent Live Eval Plan

## Goal

Run a live evaluation of the current CalendarDIFF agent system across `20-50` realistic scenarios and measure:

- reliability
- latency
- safety
- auditability
- operator usefulness

This is not a static unit-test pass.
It is a live system exercise over the currently implemented agent surface:

- `context`
- `proposal`
- `approval ticket`
- `MCP`

## Important Reality Check

The current internal agent layer is mostly deterministic and workflow-driven.
It does **not** yet route proposal generation through a separate agent-model runtime.

Implication:

- the primary eval focus should be:
  - API correctness
  - proposal/ticket behavior
  - latency
  - drift handling
  - audit integrity
- agent-specific `token/cache` metrics are **not** a meaningful primary KPI yet
- if/when agent proposal generation becomes model-backed later, add a second eval layer for:
  - agent-model latency
  - token usage
  - cache hit rate

For this phase, the right performance metrics are runtime/control-plane metrics, not LLM usage.

## Eval Scope

### In scope

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
- public MCP access to the same capabilities

### Out of scope

- `Families` agent execution
- `Manual` agent execution
- Telegram/WeChat channel actions
- true agent-model token/cache measurement

## Success Criteria

The eval is successful if it proves all of the following:

1. agent context endpoints stay consistent with product truth
2. proposals are created deterministically and auditable
3. approval tickets only execute allowed low-risk actions
4. stale / drifted targets are rejected safely
5. public MCP access is user-scoped and token-scoped
6. operator-facing latency stays acceptable across normal usage

## Scenario Count

Recommended first run:

- `32 scenarios`

This sits in the middle of the requested `20-50` range and gives enough coverage without turning into blind combinatorics.

## Scenario Matrix

## Group A. Workspace Context (`6`)

1. workspace posture = `baseline_import`
2. workspace posture = `initial_review`
3. workspace posture = `monitoring_live`
4. workspace posture = `attention_required` because of source runtime
5. workspace with top pending changes present
6. workspace with no pending changes and no blockers

Assertions:

- `recommended_next_action` matches `changes/summary.workspace_posture.next_action`
- `blocking_conditions` are present only when expected
- top pending changes are consistent with `GET /changes`

## Group B. Change Context (`8`)

7. replay `due_changed` pending change
8. baseline `created` pending change
9. removed high-risk pending change
10. already approved change
11. change with before+after evidence
12. change with missing `after` evidence
13. change with high-risk `review_carefully`
14. non-existent change id

Assertions:

- context load succeeds/fails correctly
- `recommended_next_action` aligns with `decision_support`
- high-risk items show blocking/warning state
- missing change returns clean `404`

## Group C. Change Proposal (`6`)

15. proposal for replay `due_changed`
16. proposal for baseline `created`
17. proposal for removed change
18. proposal for already reviewed change
19. repeated proposal creation on same pending change
20. proposal fetch by id

Assertions:

- proposal persisted
- proposal status starts `open`
- summary/reason/risk are populated
- already reviewed change returns `409`
- repeated proposal creation is traceable and auditable

## Group D. Approval Tickets for Change (`6`)

21. create ticket from executable `approve` proposal
22. confirm ticket successfully
23. re-confirm same executed ticket (idempotent)
24. cancel open ticket
25. confirm canceled ticket (rejected)
26. drifted change confirm (change state changed before confirm)

Assertions:

- ticket persisted with snapshot/hash
- executed ticket changes business truth
- canceled ticket does not execute
- drifted ticket returns conflict and does not write

## Group E. Source Context + Proposal (`6`)

27. source recovery: runtime failed -> `retry_sync`
28. source recovery: OAuth disconnected -> `reconnect_gmail`
29. source recovery: bootstrap running -> `wait`
30. source recovery: baseline review required -> `wait`
31. source recovery: active sync -> `wait`
32. non-existent source id

Assertions:

- context load succeeds/fails correctly
- proposal reflects the correct action family
- only `run_source_sync` proposals become executable
- web-only source actions are explicitly non-executable

## Optional Group F. Public MCP (`+6`, if pushing toward `38`)

33. MCP request without token -> `401`
34. MCP request with revoked token -> rejected
35. MCP request with valid token for user A cannot access user B state
36. MCP context tool for workspace succeeds
37. MCP proposal tool succeeds
38. MCP confirm ticket succeeds for low-risk action

Assertions:

- user scoping works
- Bearer auth gates the endpoint
- MCP execution follows the same ticket rules as HTTP

## Metrics

## A. Core live metrics

Collect for every scenario:

- `scenario_id`
- `category`
- `success`
- `http_status` or `mcp_result`
- `started_at`
- `finished_at`
- `elapsed_ms`

## B. Reliability metrics

- context success rate
- proposal creation success rate
- ticket creation success rate
- ticket confirm success rate
- drift rejection rate
- unauthorized rejection rate
- idempotent re-confirm correctness rate

## C. Latency metrics

Track separately by operation:

- workspace context latency
- change context latency
- source context latency
- proposal creation latency
- ticket creation latency
- ticket confirm latency
- ticket cancel latency
- MCP round-trip latency

Report:

- p50
- p95
- max

## D. Safety metrics

- `unsafe_execution_count`
  - should stay `0`
- `executed_without_ticket_count`
  - should stay `0`
- `drifted_but_executed_count`
  - should stay `0`
- `non_executable_proposal_ticket_created_count`
  - should stay `0`

## E. Audit quality metrics

Check that every proposal/ticket action leaves:

- proposal row
- ticket row, if created
- terminal ticket status when applicable
- executed result payload when confirmed

Report:

- proposal persistence completeness
- ticket persistence completeness
- business-side state update completeness

## F. Operator usefulness metrics

These are manual/lightly judged metrics:

- was the recommendation understandable
- was the risk level plausible
- did the result explain why execution was blocked

Use a 4-point scale:

- `clear`
- `acceptable`
- `confusing`
- `blocking`

## Log And Audit Outputs

For one eval run, write all artifacts under:

- `output/agent-live-eval-<timestamp>/`

Required files:

- `scenario-plan.json`
  - full scenario matrix
- `scenario-results.jsonl`
  - one JSON object per scenario
- `api-trace.jsonl`
  - request/response level trace for HTTP eval steps
- `mcp-trace.jsonl`
  - tool/resource level trace for MCP steps
- `proposal-audit.json`
  - snapshot of proposal rows relevant to the run
- `ticket-audit.json`
  - snapshot of approval ticket rows relevant to the run
- `SUMMARY.md`
  - human-readable eval summary
- `SUMMARY.json`
  - machine-readable aggregate metrics

Optional:

- `console.log`
- `server.log`
- `screens/` if a small UI-assisted spot-check is included

## Trace Schema

### `scenario-results.jsonl`

Each line should contain:

- `scenario_id`
- `name`
- `category`
- `surface`
  - `http`
  - `mcp`
- `target_kind`
- `target_id`
- `expected_outcome`
- `actual_outcome`
- `success`
- `elapsed_ms`
- `request_ids`
- `proposal_id`
- `ticket_id`
- `notes`

### `api-trace.jsonl`

Each line should contain:

- `scenario_id`
- `method`
- `path`
- `request_body`
- `status_code`
- `response_excerpt`
- `elapsed_ms`

### `mcp-trace.jsonl`

Each line should contain:

- `scenario_id`
- `kind`
  - `tool`
  - `resource`
- `name`
- `arguments`
- `result_excerpt`
- `elapsed_ms`

## Test Flow

## Phase 0. Preflight

1. verify backend health
2. verify MCP endpoint health/auth behavior
3. prepare one or more test users
4. seed required change/source states
5. capture a seeded snapshot for reproducibility

## Phase 1. HTTP control-plane eval

Run Groups A-E directly against public/backend HTTP APIs.

Reason:

- establish a stable backend baseline before adding MCP transport variability

## Phase 2. MCP live eval

Run Group F and selected overlap cases via MCP:

- workspace context
- change proposal
- change ticket confirm
- source proposal
- source ticket confirm

Reason:

- compare transport-layer behavior against the same backend semantics

## Phase 3. Audit snapshot

At the end of the run:

1. query proposal rows created during eval
2. query approval tickets created during eval
3. verify terminal business objects reflect expected outcomes
4. write aggregate summaries

## Seed Strategy

Use a dedicated eval account namespace, for example:

- `agent-eval-<timestamp>@example.com`

Seed only the minimum needed states:

- one baseline review change
- one replay due-change
- one removed/high-risk change
- one runtime-failed source
- one OAuth-disconnected source
- one bootstrap-running source

Do not depend on a full-year replay run for this eval.

Full-year replay is useful for system stability.
This eval is for the agent/control plane.

## Execution Recommendation

Run the `32` scenarios in this order:

1. context read scenarios
2. proposal scenarios
3. ticket create/confirm/cancel scenarios
4. MCP transport scenarios

This minimizes cascading state pollution.

## Pass / Fail Thresholds

### Must-pass

- `unsafe_execution_count = 0`
- `executed_without_ticket_count = 0`
- `drifted_but_executed_count = 0`
- `non_executable_proposal_ticket_created_count = 0`

### Strong target

- proposal creation success rate `>= 95%`
- ticket confirm success rate `>= 95%` on executable scenarios
- unauthorized / revoked token rejection rate `= 100%`
- p95 context latency `< 800 ms`
- p95 proposal latency `< 1200 ms`
- p95 ticket confirm latency `< 1200 ms`

## Follow-up Use

This eval should be rerun:

- before widening agent execution scope
- before adding Telegram/WeChat channels
- before adding `Families` or `Manual` execution
- before changing MCP auth or public exposure
