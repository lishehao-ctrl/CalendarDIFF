# Backend Agent Workflow

## Purpose

This file defines the default workflow for backend-only architecture cleanup and refactor tasks in CalendarDIFF.

Use this workflow when:

- the task is backend-only
- frontend changes should be intentionally deferred
- a coding agent should execute from a written spec
- the executing agent should leave a written report for later review

## Default Process

Every backend-only cleanup pass should follow this loop:

1. write a narrowly scoped task spec in a root-level markdown file
2. write a root-level prompt that tells the executing agent to read the spec
3. give the executing agent a dedicated root-level report file path
4. the executing agent derives its own execution plan from the spec
5. the executing agent implements the change
6. the executing agent writes its outcome back into the report file
7. a reviewer agent reads the report file and then verifies the actual diff/tests

## Scope Discipline

For these backend-only passes:

- do not change frontend code unless the spec explicitly says to do so
- if an interface is still moving, prefer stabilizing backend contracts first
- docs may be updated if they describe backend runtime behavior

## File Pattern

For each pass, create:

- `*_SPEC.md`
- `*_AGENT_PROMPT.md`
- `*_AGENT_REPORT.md`

The report file should be updated by the executing agent instead of only sending a chat summary.

## Report Requirements

The executing agent should write the report in markdown with these sections:

1. `Result`
2. `Execution Plan`
3. `Changes Made`
4. `Validation`
5. `Risks / Remaining Issues`

The reviewer agent should treat the report as a guide, not as the only source of truth.

Actual code, diff, and tests must still be checked.

## Validation Bias

For backend-only passes:

- backend tests are required
- targeted compile/import sanity is encouraged
- frontend `typecheck`, `lint`, and `build` may still be run as a repo guard, even if frontend was intentionally untouched

## Design Bias

When the spec has already picked a direction:

- prefer one hard invariant over permissive fallback logic
- prefer explicit error isolation over silent degradation
- prefer backend contract clarity before UI adaptation
