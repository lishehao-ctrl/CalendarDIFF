# Data Flow Hardening Spec

## 1. Purpose

This document defines the next cleanup pass for CalendarDIFF after the entity-first semantic refactor.

The goal is not another broad architecture redesign. The goal is to make the current data flow unambiguous for future development.

This spec exists because the main path is already mostly clear, but three areas still create confusion:

1. the observation payload contract is not fully single-shaped
2. family label authority is not fully decided in code
3. the canonical edit branch is not in a trustworthy state

If older code, docs, or tests conflict with this file, follow this file.

## 2. Current Mainline Data Flow

The intended main path is:

`input_sources -> parser records -> source_event_observations -> pending proposal rebuild -> changes -> approve into event_entities -> notifications`

This main path should remain intact.

This pass is about removing ambiguity around the supporting contracts and edit branch so future work can build on a stable foundation.

## 3. Problems To Fix

## 3.1 Observation payload contract is still mixed

Current reality:

- parser output is centered on top-level `source_facts + semantic_event_draft + link_signals`
- apply steps build observation payloads containing top-level `source_facts + semantic_event + link_signals + kind_resolution`
- several readers still look for older `enrichment` fields or alternate payload shapes

This means future developers still have to guess:

- which payload shape is authoritative
- whether `semantic_event_draft` or `semantic_event` is the stable runtime field
- whether `enrichment` is still an active contract or only legacy compatibility

## 3.2 Family label authority is still mixed

The product decision from the user is:

- users should see the latest family label everywhere

That means the repo should converge to:

- `family_id` is the only label authority
- current display resolves latest `course_work_item_label_families.canonical_label`
- `event_entities.family_name` should not remain as a competing display authority

Today this is still mixed:

- `event_entities.family_name` is persisted
- docs partly describe frozen names
- display code sometimes uses payload `family_name`, sometimes resolves latest label

## 3.3 Canonical edit branch is not trustworthy

There are unresolved merge-conflict markers and syntax errors in the canonical edit flow.

This is not just cosmetic. It means a future developer cannot trust:

- preview flow
- apply transaction
- snapshot/target/audit helpers

The canonical edit path must either be repaired cleanly or explicitly reduced, but it cannot remain half-broken.

## 4. Required Decisions

These are fixed by this spec and should not be re-litigated in the implementation pass.

### 4.1 Single observation envelope

The active observation payload shape must be:

```json
{
  "source_facts": { ... },
  "semantic_event": { ... },
  "link_signals": { ... },
  "kind_resolution": { ... }
}
```

Rules:

- `semantic_event` is the only approved observation-level semantic payload
- `semantic_event_draft` is parser-stage only
- parser output may still emit `semantic_event_draft`, but apply/runtime must normalize it into `semantic_event`
- `enrichment` is no longer an active runtime observation contract

### 4.2 Label authority

The user-facing rule is:

- users always see the latest family label

Therefore:

- `family_id` is the only label authority
- current UI display resolves family text from latest `canonical_label`
- `changes` may keep frozen `family_name` only as audit payload, not as default display authority
- `event_entities.family_name` should be removed from the active model if feasible in this pass

If full column removal is too invasive for this pass, the minimum acceptable outcome is:

- `event_entities.family_name` remains only as deprecated snapshot storage
- all user-facing display paths ignore it and resolve latest label from `family_id`
- docs explicitly mark it deprecated and non-authoritative

### 4.3 Canonical edit semantics

The canonical edit route family may keep the word `canonical` for route stability, but internally it must mean:

- direct edit of approved entity state

The canonical edit code path must:

- target `entity_uid`
- load approved entity semantic payload
- build edited semantic payload
- write through the shared approved-entity write path
- emit audit change rows
- reject conflicting pending changes for the same `entity_uid`

No old `Input/Event` semantics may survive inside this branch.

## 5. Required Implementation Work

## 5.1 Repair the canonical edit branch first

Files to fix:

- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_target.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_target.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_audit.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_audit.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_builder.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_builder.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_preview_flow.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_preview_flow.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_apply_txn.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_apply_txn.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_snapshot.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_snapshot.py)

Requirements:

1. remove all merge markers
2. remove all dead legacy branch code
3. make the files compile
4. keep only the entity-first semantic implementation path
5. ensure imports do not reference removed legacy helpers

Acceptance:

- no `<<<<<<<`, `=======`, `>>>>>>>` markers remain
- `py_compile` passes for these files
- canonical edit tests pass or are updated to the repaired branch

## 5.2 Collapse payload contract to a single runtime shape

Files likely involved:

- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/payload_extractors.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/payload_extractors.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/calendar_apply.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/calendar_apply.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/gmail_apply.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/gmail_apply.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/observation_store.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/observation_store.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/pending_proposal_rebuild.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/pending_proposal_rebuild.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/linking_rules.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/linking_rules.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/label_learning_service.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/label_learning_service.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/users/course_work_item_families_service.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/users/course_work_item_families_service.py)

Requirements:

1. define one active observation envelope contract
2. observation readers should read from that shape only
3. remove runtime fallback to `payload.enrichment.*` for the mainline path
4. remove runtime ambiguity between `semantic_event_draft` and `semantic_event`
5. keep parser outputs stable, but normalize them into the runtime shape immediately in apply

Acceptance:

- mainline runtime no longer depends on `payload.enrichment.*`
- observation-derived behavior reads `semantic_event`
- docs describe one active observation envelope

## 5.3 Make family label authority explicit in code

Files likely involved:

- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/approved_entity_state.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/approved_entity_state.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/common/family_labels.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/common/family_labels.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/common/event_display.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/common/event_display.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/common/semantic_codec.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/common/semantic_codec.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/change_listing_service.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/change_listing_service.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_snapshot.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_snapshot.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/common.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/common.py)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/review-change-edit-page-client.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/review-change-edit-page-client.tsx)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/presenters.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/presenters.ts)

Requirements:

1. current user-facing display must resolve latest family label from `family_id`
2. remove `event_entities.family_name` as an active display authority
3. if the column remains temporarily, treat it as deprecated snapshot only
4. review list, canonical edit, link review, and presenters must all follow the same label rule
5. docs must explicitly say that users see the latest label everywhere

Optional stronger cleanup:

- remove `family_name` from `EventEntity`
- remove assignment to `existing.family_name` in the approved write path

Acceptance:

- there is one clear label rule in both code and docs
- user-facing display no longer depends on `event_entities.family_name`

## 5.4 Sync docs to the real flow

Docs to update:

- [/Users/lishehao/Desktop/Project/CalendarDIFF/docs/architecture.md](/Users/lishehao/Desktop/Project/CalendarDIFF/docs/architecture.md)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/docs/event_contracts.md](/Users/lishehao/Desktop/Project/CalendarDIFF/docs/event_contracts.md)
- [/Users/lishehao/Desktop/Project/CalendarDIFF/docs/dataflow_input_to_notification.md](/Users/lishehao/Desktop/Project/CalendarDIFF/docs/dataflow_input_to_notification.md)

Requirements:

1. describe one active observation payload shape
2. remove outdated `enrichment(...)` runtime descriptions
3. document the latest-label-everywhere rule
4. document canonical edit as approved entity editing, not legacy canonical input/event editing

## 6. Non-Goals

Do not do these in this pass:

- do not redesign the whole semantic model again
- do not reintroduce legacy `Input/Event/Snapshot` compatibility
- do not add caching work
- do not change main route families
- do not start a new projection-table project unless required to support the decisions above

## 7. Validation

At minimum, run:

```bash
rg -n "^(<<<<<<<|=======|>>>>>>>)" app/modules/review_changes
```

```bash
python -m py_compile \
  app/modules/review_changes/canonical_edit_target.py \
  app/modules/review_changes/canonical_edit_audit.py \
  app/modules/review_changes/canonical_edit_builder.py \
  app/modules/review_changes/canonical_edit_preview_flow.py \
  app/modules/review_changes/canonical_edit_apply_txn.py \
  app/modules/review_changes/canonical_edit_snapshot.py
```

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_review_edits_api.py \
  tests/test_review_canonical_edit_boundaries.py \
  tests/test_review_canonical_edit_flow_boundaries.py \
  tests/test_review_change_source_summary_api.py \
  tests/test_review_items_summary_api.py \
  tests/test_review_label_learning_api.py \
  tests/test_review_link_candidates_api.py \
  tests/test_review_link_alerts_api.py
```

If frontend display code is touched, also run:

```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```

## 8. Done Definition

This pass is complete only if all of the following are true:

1. canonical edit files are conflict-free and compile
2. there is one active observation runtime envelope
3. mainline runtime no longer depends on `enrichment` fallback
4. latest family label is the only user-facing label authority
5. docs match the real runtime behavior

