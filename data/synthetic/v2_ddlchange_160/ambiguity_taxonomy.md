# Ambiguity Taxonomy (`v2_ddlchange_160`)

This taxonomy is used by both mail and ICS annotations.

## Labels

1. `relative_time_no_tz`
- Relative time phrase without explicit date/timezone, such as "this Friday midnight".

2. `missing_timezone`
- Absolute-looking time appears but timezone is omitted or implied.

3. `timezone_abbrev_conflict`
- Timezone abbreviation can be interpreted differently or conflicts with known source timezone.

4. `dual_due_dates_old_new_unclear`
- Two timestamps appear but old/new mapping is unclear.

5. `tentative_language`
- Soft wording ("likely", "tentative", "possibly delayed") weakens certainty.

6. `forwarded_thread_conflict`
- Forwarded/replied context includes contradictory scheduling statements.

7. `multi_course_collision`
- One message references multiple courses with potentially different deadlines.

8. `datetime_typo_or_impossible`
- Invalid or suspicious timestamp (impossible date/time, typo, partial date).

9. `grace_period_soft_deadline`
- Hard due date vs grace period semantics are mixed.

10. `holiday_shift_unspecified`
- Deadline shift references holiday closure without final resolved timestamp.

11. `removed_vs_cancelled_unclear`
- Snapshot disappearance may be cancellation, migration, or temporary suppression.

12. `course_alias_mismatch`
- Course identifier aliases conflict (e.g., `CSE 101` vs `CSE 101A`).

## Annotation Rules

- `is_ambiguous=true` rows must include:
  - at least one `ambiguity_tags` entry,
  - `alternative_interpretation`,
  - explicit `review_notes`.
- `is_ambiguous=false` rows must set:
  - `ambiguity_tags=[]`,
  - `alternative_interpretation=null`.

## Coverage Requirement

- Each label above appears at least `3` times across all ambiguous rows in this dataset.

## Longform Priority Rules

When longform text contains both strict and soft wording:

1. Prioritize explicit task/timestamp anchors over conversational qualifiers.
2. Prioritize UID-linked structural fields in ICS over narrative commentary.
3. Keep exactly one primary interpretation compatible with gold labels.
4. Keep alternative interpretations in ambiguity metadata only; do not invert the main label by prose drift.
