# Family Label Authority Spec

## 1. Purpose

This document is a narrow follow-up spec for CalendarDIFF.

It exists to lock down one specific product and architecture rule:

- users should always see the latest family label everywhere

This file should be read on top of:

- `/Users/lishehao/Desktop/Project/CalendarDIFF/ENTITY_FIRST_SEMANTIC_SPEC.md`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/DATA_FLOW_HARDENING_SPEC.md`

If older code, docs, tests, or helper behavior conflict with this file, follow this file.

## 2. Fixed Product Decisions

These decisions are already made and should not be re-litigated in implementation.

### 2.1 Stable identity

- `family_id` is the only stable family identity
- labels are mutable
- display names must not be treated as identity

### 2.2 Latest-label display everywhere

- all user-facing surfaces must show the latest family label
- this includes review lists, review details, review edit flows, link review, notifications, digests, and any other user-facing event display
- historical records do not keep showing the old label by default
- after a rename, the new label should appear globally

### 2.3 No hard delete

- family rows must not be hard-deleted as a normal product path
- a family must always retain at least one valid label
- if a family row becomes unresolvable, that is a data-integrity bug, not a normal display case

Because of this rule:

- `"Unknown"` is not a valid intended product-state fallback for normal user display
- fallback-to-snapshot names should not be used to paper over missing authority rows

### 2.4 Changes table semantics

`changes` refers to the review/audit proposal records that power `/review/changes`.

It stores change metadata such as:

- `entity_uid`
- `change_type`
- semantic before/after payloads
- review status
- evidence
- source refs

For family label authority:

- `changes` may still contain frozen `family_name` inside semantic/evidence payloads for audit purposes
- those frozen names are not the default display authority
- default display must resolve latest label from `family_id`

### 2.5 Family rebuild side path

The `course_work_item_family_rebuild` side path may remain temporarily, but it is not the target end-state.

Future direction is fixed:

- this side path should eventually be cleaned so it no longer reconstructs parser-stage family payload shapes unnecessarily
- it should converge to the same active runtime contracts as the main data flow

This is a follow-up task, not required in the same pass unless implementation naturally reaches it.

## 3. Required Architecture Rules

### 3.1 One label authority

The only authoritative source for current family display text is:

- `course_work_item_label_families.canonical_label` resolved by `family_id`

No other persisted field may compete with this authority for default user-facing display.

### 3.2 Event entity behavior

For approved entity state:

- `event_entities` should rely on `family_id` as the durable family reference
- `event_entities.family_name` must not be used as an active display authority

Preferred end-state:

- remove `event_entities.family_name`

Minimum acceptable intermediate state:

- keep the column only as deprecated storage
- do not use it for default display
- do not write new code that depends on it for user-facing rendering

### 3.3 Change/read-model behavior

For review and audit records:

- display presenters must resolve family labels from latest authority by `family_id`
- if frozen `family_name` still exists in change payloads, treat it as audit-only
- do not prefer frozen names over latest authority in normal UI

### 3.4 Notification behavior

- notifications and digests must also resolve the latest family label
- rename effects should flow through to notification rendering the same way they do for review views

### 3.5 Data integrity expectation

Because families are not hard-deletable:

- code paths should prefer failing loudly, logging clearly, or surfacing a data-integrity problem over silently treating missing family rows as a normal product case
- do not add new snapshot-label fallbacks as a convenience layer

## 4. Required Cleanup Work

### 4.1 Remove label-authority ambiguity

Likely files:

- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/common/family_labels.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/common/semantic_codec.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/common/event_display.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/change_listing_service.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/edit_service.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/canonical_edit_snapshot.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/common.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/notify/`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/presenters.ts`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/`

Requirements:

1. latest family label must be resolved from `family_id`
2. snapshot `family_name` must not drive default display
3. rename should affect all user-facing displays consistently
4. `"Unknown"` should not remain positioned as an expected normal-state fallback if the family row should always exist

### 4.2 Tighten family lifecycle rules

Likely files:

- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/users/course_work_item_families_service.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/db/models/shared.py`
- related routers/tests/docs

Requirements:

1. normal product flows should not hard-delete families
2. if a delete operation exists, replace it with a safe guard, a rename flow, or a disallowed operation
3. document and test the invariant that a family must remain resolvable

### 4.3 Keep audit data separate from display authority

Requirements:

1. if frozen family names remain inside `changes`, evidence, or snapshots, document them as audit-only
2. do not read those frozen names as the first-choice UI label
3. if a cleanup pass can remove redundant frozen label fields safely, that is preferred

### 4.4 Future cleanup target

After the label-authority pass is stable:

- clean `course_work_item_family_rebuild` so it converges to the same active runtime contracts as the mainline flow

This is a planned follow-up and should be called out explicitly if not done in the current pass.

## 5. Acceptance Criteria

The pass is successful when all of the following are true:

1. there is exactly one default display authority for family labels: latest label by `family_id`
2. user-facing review, edit, link, and notification surfaces all follow the same label rule
3. family rows are no longer treated as normally deletable
4. docs clearly state that rename updates display globally
5. any remaining frozen family-name storage is explicitly marked audit-only or deprecated

## 6. Suggested Validation

At minimum, run the tests most likely to exercise label resolution and review rendering, for example:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_review_items_summary_api.py \
  tests/test_review_change_source_summary_api.py \
  tests/test_review_label_learning_api.py \
  tests/test_review_edits_api.py \
  tests/test_review_link_candidates_api.py \
  tests/test_review_link_alerts_api.py \
  tests/test_notify_jsonl_sink.py
```

If frontend presenters or review UI are touched, also run:

```bash
cd /Users/lishehao/Desktop/Project/CalendarDIFF/frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```

## 7. Implementation Bias

When choosing between compatibility and clarity, prefer clarity.

Specifically:

- prefer one authoritative source over snapshot fallbacks
- prefer explicit invariants over permissive fallback display strings
- prefer deleting redundant display-state storage over keeping multiple semi-authoritative names around
