# Table Ownership

This document describes module ownership inside the monolith.

## Input and source state
- `sources`
  - `input_sources`
  - `input_source_configs`
  - `input_source_cursors`
  - `input_source_secrets`
  - source sync request state

## Runtime state
- `runtime.connectors`
  - raw fetch / replay/bootstrap continuation state
  - provider discovery payloads
- `runtime.llm`
  - parser coordination state
  - parse / reduce task execution state
- `runtime.apply`
  - `source_event_observations`
  - `changes`
  - approved apply transitions
- `runtime.kernel`
  - shared queue, retry, result handoff, and sync stage state

## Review state
- `changes`
  - review decisions, viewed markers, canonical edits, label learning
- `families`
  - course family / raw-type mapping tables

## Product state
- `manual`
  - manual event mutations routed through approved entity state
- `settings`
  - user profile settings stored on `users`
- `notify`
  - notification outbox / digest delivery state
