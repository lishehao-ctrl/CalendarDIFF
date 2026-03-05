# Synthetic Dataset: `ddlchange_160`

This dataset is a fully synthetic benchmark for deadline-change extraction and diff robustness.

## Scope

- Total samples: `160`
- Mail samples: `120`
- ICS snapshot pairs: `40` (`before` + `after`)
- Ambiguous samples: `56` (`35%`)
  - Mail ambiguity: `42`
  - ICS ambiguity: `14`

## Directory Layout

- `dataset_manifest.json`: frozen distribution target and metadata.
- `ambiguity_taxonomy.md`: ambiguity label definitions.
- `mail/raw_mail_120.jsonl`: raw mail input (`email_id`, `from`, `subject`, `date`, `body_text`).
- `mail/gold_mail_120.jsonl`: gold labels, strictly aligned with `tools/labeling/schema/email_label.json`.
- `mail/ambiguity_mail_120.jsonl`: ambiguity annotations for every mail sample.
- `ics/pairs/*.ics`: before/after snapshot files (`40` pairs, `80` files).
- `ics/pair_index_40.jsonl`: pair metadata (`pair_id`, paths, course hints).
- `ics/gold_diff_40.jsonl`: expected diff class and changed UID labels.
- `ics/ambiguity_40.jsonl`: ambiguity annotations for every ICS pair.
- `qa/review_log_mail.jsonl`: manual review audit log for mail.
- `qa/review_log_ics.jsonl`: manual review audit log for ICS.
- `qa/validation_report.json`: output report from validation script.
- `longform_rewrite_spec.md`: decision-locked rewrite rules for longform payloads.
- `archive/pre_longform_20260302/`: baseline snapshot before longform rewrite.

## Locked Distribution

### Mail

- `KEEP=86`, `DROP=34`
- KEEP event types:
  - `deadline=30`
  - `exam=12`
  - `schedule_change=18`
  - `assignment=12`
  - `action_required=8`
  - `announcement=4`
  - `grade=2`
- DROP buckets:
  - `digest/newsletter/noise=12`
  - `grade-only non-actionable=8`
  - `generic announcement=8`
  - `admin/social noise=6`

### ICS

- `DUE_CHANGED=18` (ambiguous `7`)
- `CREATED=10` (ambiguous `2`)
- `NO_CHANGE=6` (ambiguous `0`)
- `REMOVED_CANDIDATE=6` (ambiguous `5`)

## Data Rules

- Mail gold rows must satisfy `tools/labeling/schema/email_label.json`.
- For mail:
  - `DROP -> event_type=null, action_items=[], raw_extract fields are null`
  - `KEEP -> event_type must be valid enum, confidence in [0,1]`
- ICS diff enum is fixed:
  - `CREATED | DUE_CHANGED | NO_CHANGE | REMOVED_CANDIDATE`
- `REMOVED_CANDIDATE` is intentionally marked as history-dependent removal candidate.

## Longform V2 Profile

- Rewrite date: `2026-03-02`
- Scope:
  - `mail/raw_mail_120.jsonl`
  - `ics/pairs/*.ics`
- Mail longform constraints:
  - per-sample length `900-1600`
  - recommended median `>=1100`
  - recommended p90 `<=1600`
- ICS longform constraints:
  - per-VEVENT `DESCRIPTION` length `450-900`
  - recommended median `>=550`
- Semantic rule:
  - keep one dominant conclusion per sample, aligned with existing gold labels.
- Compatibility:
  - no schema changes in gold/ambiguity files.

## Language Mix Constraint

- English-first style with mixed Chinese-English samples.
- Target ratio is fixed at `85% English / 15% mixed`.
- This dataset encodes exactly `24` mixed-language samples out of `160`.

## Validation

Run:

```bash
python scripts/validate_synthetic_dataset.py
```

Optional:

```bash
python scripts/validate_synthetic_dataset.py \
  --dataset-root data/synthetic/ddlchange_160 \
  --schema tools/labeling/schema/email_label.json \
  --report data/synthetic/ddlchange_160/qa/validation_report.json
```

The script exits non-zero on validation errors and writes a structured report.

Longform validation report includes:

- `mail_body_length_stats`
- `ics_description_length_stats`
- `intra_subject_similarity_max`
- `semantic_guardrail_pass_rate`
