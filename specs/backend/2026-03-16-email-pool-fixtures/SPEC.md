# Email Pool Fixtures Spec

## Purpose

Create a maintainable private email-pool fixture architecture for Gmail-side parser evaluation.

The pool should support two complementary needs:

1. synthetic positive samples for `ddlchange` cases that are too rare in real historical email
2. real Gmail samples collected via existing OAuth source so parser quality can be tested against realistic background noise

## Product Intent

CalendarDIFF is trying to detect grade-relevant time signals that affect the canonical event-time database.

For Gmail testing, we need a fixture pool that supports:

1. high-recall testing on known positive `ddlchange` samples
2. precision testing against a large set of real non-`ddlchange` mail
3. repeatable mixed-set evaluations where synthetic positives are blended into real Gmail negatives

## Required End State

Create a private fixture root under:

- `tests/fixtures/private/email_pool/`

Inside it, create exactly these subdirectories:

1. `tests/fixtures/private/email_pool/synthetic_ddlchange/`
2. `tests/fixtures/private/email_pool/oauth_random_300/`
3. `tests/fixtures/private/email_pool/oauth_filtered_150/`

Each directory must contain:

1. `manifest.json`
2. `samples.jsonl`
3. `README.md`

## Data Meaning

### `synthetic_ddlchange`

Contains about 30 generated Gmail-like samples that are known positive cases.

Scope:

1. explicit newly announced graded item with clear time
2. explicit due-date / due-time change
3. explicit quiz / exam reschedule
4. explicit bulk rule affecting multiple existing monitored items

These are positive fixtures for parser recall and behavior regression.

### `oauth_random_300`

Contains about 300 real Gmail samples pulled through the existing Gmail OAuth source without the product filter.

Purpose:

1. large background-noise pool
2. realistic negative or mixed examples
3. sampling base for precision checks

Assumption:

- use current active Gmail source `id=2` unless a better discovery method is already in repo

### `oauth_filtered_150`

Contains about 150 real Gmail samples pulled through the same OAuth source after a simple broad filter.

The user-specified broad filter intent is:

1. inbox mail
2. metadata and/or subject/body containing course-like markers

Default practical interpretation for this pass:

1. label includes `INBOX`
2. message text contains at least one course-like token, using a broad regex or token list such as:
   - `course`
   - `quiz`
   - `exam`
   - `midterm`
   - `final`
   - `homework`
   - `assignment`
   - `project`
   - `problem set`
   - department-number forms like `CSE`, `MATH`, `CHEM`, `PHYS`, etc.

This directory is not meant to be parser-precise. It is meant to be a denser, still realistic, semi-relevant pool.

## Sample Format

Use one JSON object per line in `samples.jsonl`.

Each sample object must contain:

1. `sample_id`
2. `sample_source`
3. `message_id`
4. `thread_id`
5. `subject`
6. `from_header`
7. `snippet`
8. `body_text`
9. `internal_date`
10. `label_ids`
11. `collection_bucket`
12. `notes`

Additional fields by bucket:

### synthetic bucket required extras

1. `expected_mode`
2. `expected_record_type`
3. `expected_semantic_event_draft`
4. `expected_directive`

### real OAuth buckets required extras

1. `filter_reason`
2. `source_id`

## Privacy and Safety Rules

This pass must stay under `tests/fixtures/private/`.

Do not place collected Gmail content under public fixture paths.

Do not store attachments.

Do not store raw HTML if plain text is already available.

Body text should be plain text only.

If a message body is extremely large, truncate conservatively and note truncation in `notes`.

## Collection Rules

### Synthetic

Use the separate agent-generated positive set the user already requested.

Normalize it into the required `samples.jsonl` structure.

### OAuth random 300

Use Gmail OAuth access through the current repo stack.

Sampling rules:

1. collect from current authenticated mailbox through existing Gmail source
2. avoid duplicate `message_id`
3. prefer most recent active-term mail unless the mailbox does not have enough volume
4. do not silently substitute filtered mail for the random bucket

### OAuth filtered 150

Use a broad course-like filter, not the current tight product filter.

This is important:

1. this bucket should remain broader than `matches_gmail_source_filters()`
2. it should include many false positives and edge cases
3. it should not collapse into only obvious `ddlchange` mail

## Implementation Guidance

Likely backend files to touch:

1. add one collection script under `scripts/`
2. possibly add one small helper module under `app/modules/ingestion/` or `tools/`
3. do not change frontend

Recommended script shape:

1. support `--bucket synthetic|oauth_random_300|oauth_filtered_150|all`
2. support `--source-id`
3. support `--scan-limit`
4. support deterministic sampling via `--seed`

## Acceptance Criteria

1. fixture root exists at `tests/fixtures/private/email_pool/`
2. three required bucket directories exist
3. each bucket has `manifest.json`, `samples.jsonl`, and `README.md`
4. `synthetic_ddlchange` contains about 30 samples
5. `oauth_random_300` contains about 300 samples unless mailbox volume is insufficient
6. `oauth_filtered_150` contains about 150 samples unless mailbox volume is insufficient
7. all sample records are valid JSON and consistent with the documented schema
8. no duplicate `message_id` within each OAuth bucket
9. all collected data remains under private fixture paths only

## Non-Goals

1. do not tune parser prompts in this pass
2. do not build the mixed-set evaluator in this pass
3. do not change Gmail detection semantics in this pass
4. do not add public docs for private fixture contents
