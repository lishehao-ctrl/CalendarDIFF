# Backend Family ID Invariant Spec

## 1. Purpose

This spec defines the next backend-only hardening pass after the family-label authority cleanup.

This pass exists because the display side now correctly treats missing `family_id` as a data-integrity error, but the ingest/write side still allows some records to flow through without a resolved `family_id`.

That mismatch must be removed.

Frontend is explicitly out of scope for this pass.

## 2. Fixed Product Decisions

These decisions are already made.

### 2.1 Family is always required for normal event flow

For any event that successfully enters the normal semantic/review flow:

- `family_id` must exist
- `family_id` must be stable identity
- the default family behavior is: incoming raw type becomes its own family if needed

There is no normal “reviewable event without family” state.

### 2.2 Missing course identity is the only allowed unresolved case

If an incoming record does not have enough course identity to create or resolve a family, it must not enter the normal review flow.

That means:

- no normal `Change`
- no `/review/changes` entry
- no notification enqueue
- no pretending the record is valid-but-unclassified

Instead, it must be isolated into an ingest-side unresolved/error bucket.

### 2.3 Backend-only pass

This pass must not modify frontend code.

If the backend API shape changes only in ways that frontend does not yet consume, that is acceptable.

The priority is backend correctness and isolation first.

## 3. Required End State

The backend must converge to this rule:

- every normal `source_event_observation`
- every normal semantic proposal in `changes`
- every approved `event_entity`

must have a resolved `family_id`.

If course identity is missing or unusable:

- the record is stored in an unresolved ingest bucket
- the record does not participate in review proposal generation

## 4. Required Runtime Rules

### 4.1 Family resolution rule

If a record has enough course identity and a raw/event label:

- it must resolve or create a family
- the output of the normal apply path must contain `family_id`

Returning a normal runtime payload with `family_id=None` is no longer allowed.

### 4.2 Unresolved bucket rule

If a record is missing enough course identity to create or resolve a family:

- the record must be written to a backend unresolved bucket
- the unresolved bucket is an ingest/debugging surface, not a review surface
- the unresolved record should preserve enough normalized context to diagnose the failure later

Minimum preserved context:

- `user_id`
- `source_id`
- `source_kind`
- `provider`
- `external_event_id`
- `request_id`
- `reason_code`
- normalized `source_facts`
- parser-stage semantic payload if available
- observed/applied time

### 4.3 Review-flow isolation rule

Unresolved records must not:

- upsert normal `source_event_observations`
- produce pending `changes`
- emit `review.pending.created`
- enter notification enqueue

### 4.4 Recovery rule

If a later ingest for the same source/external event becomes resolvable:

- normal flow may proceed
- the unresolved bucket entry should be marked resolved, superseded, or otherwise clearly no longer active

This state transition must be explicit in the backend model.

## 5. Recommended Persistence Shape

Preferred approach:

- add a dedicated unresolved ingest table in the ingestion domain

Suggested model name:

- `IngestUnresolvedRecord`

Suggested fields:

- `id`
- `user_id`
- `source_id`
- `source_kind`
- `provider`
- `external_event_id`
- `request_id`
- `reason_code`
- `source_facts_json`
- `semantic_event_draft_json`
- `kind_resolution_json`
- `raw_payload_json`
- `is_active`
- `resolved_at`
- `created_at`
- `updated_at`

The executing agent may refine the exact column set if needed, but the model must support:

- storing unresolved records
- preventing them from polluting normal review flow
- resolving/superseding them when the same source record later becomes valid

## 6. Required Implementation Areas

Likely backend files:

- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/db/models/ingestion.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/db/migrations/`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/course_work_item_family_resolution.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/calendar_apply.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/gmail_apply.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/pending_proposal_rebuild.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/observation_store.py`
- any new helper such as an unresolved bucket service/module
- targeted backend docs if needed

## 7. Acceptance Criteria

The pass is complete when all of the following are true:

1. normal reviewable records cannot enter the backend without `family_id`
2. missing-course-identity records are isolated into an unresolved ingest bucket
3. unresolved records do not produce `changes` or notifications
4. a later resolvable ingest can clear or resolve the matching unresolved record
5. frontend remains untouched in this pass

## 8. Required Tests

At minimum, add or update tests for:

1. a valid event with course identity gets a created family and a non-null `family_id`
2. a record with missing course identity is stored in unresolved ingest state
3. unresolved ingest records do not create pending `changes`
4. unresolved ingest records do not emit `review.pending.created`
5. a later valid ingest for the same source record resolves/supersedes the unresolved record

Target areas likely include:

- `tests/test_core_ingest_pending_proposal_rebuild.py`
- calendar/gmail apply tests
- any new unresolved ingest bucket tests
- outbox contract tests if behavior changes there

## 9. Explicit Non-Goals

Do not do these in this pass:

- frontend updates
- new user-facing unresolved UI
- broad notification redesign
- unrelated payload-contract cleanup beyond what is needed for this invariant

## 10. Validation

The executing agent should derive its own exact command set from the implemented diff, but backend validation must include:

- targeted pytest for modified ingest/rebuild/outbox paths
- compile/import sanity for changed backend modules

Frontend validation may still be run as a repository guard, but frontend files should not be modified.
