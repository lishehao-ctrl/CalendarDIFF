# Table Ownership

This document describes module ownership inside the monolith.

## Input and source state
- `input_control_plane`
  - `input_sources`
  - `input_source_configs`
  - `input_source_cursors`
  - `input_source_secrets`
  - source sync request state

## Ingestion and apply state
- `ingestion`
  - raw fetch / parse scheduling state
  - queue and parser coordination state
- `core_ingest`
  - `source_event_observations`
  - `changes`
  - approved apply transitions

## Review state
- `review_changes`
  - review decisions, viewed markers, canonical edits, label learning
- `review_links`
  - `event_link_candidates`
  - `event_entity_links`
  - `event_link_blocks`
- `review_taxonomy`
  - course family / raw-type mapping tables

## Product state
- `events`
  - manual event mutations routed through approved entity state
- `profile`
  - user profile settings stored on `users`
- `notify`
  - notification outbox / digest delivery state
