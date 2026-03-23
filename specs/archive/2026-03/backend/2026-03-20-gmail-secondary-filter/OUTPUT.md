# Implementation Output Template

## Dataset Artifacts

- `data/secondary_filter/gmail_train.jsonl`
- `data/secondary_filter/gmail_eval.jsonl`
- `data/secondary_filter/gmail_shadow_candidates.jsonl`
- `data/secondary_filter/gmail_high_risk_eval.jsonl`
- `data/secondary_filter/DATASET_REPORT.md`

## Dataset Summary

- train: `12000`
- eval: `1500`
- shadow: `3000`
- high_risk_eval: `658`
- relevant_like=true total: `7560`

## Pattern Coverage

- `academic_admin_noise`: `1315`
- `academic_wrapper_with_true_change`: `838`
- `broad_audience_deadline_mutation`: `1251`
- `bulk_schedule_mutation`: `243`
- `exam_logistics_non_target`: `776`
- `exam_time_change_target`: `1013`
- `explicit_graded_item_unchanged`: `963`
- `lms_wrapper_only`: `830`
- `mixed_signal_uncertain`: `973`
- `new_graded_item_announcement`: `1047`
- `newsletter_digest_campus_weekly`: `413`
- `piazza_ed_forum_summary`: `933`
- `quoted_thread_conflict`: `1211`
- `real_due_date_change`: `1089`
- `recruiting_career_internship_bait`: `643`
- `shipping_subscription_bait`: `595`
- `stale_deadline_in_reply_chain`: `1104`
- `strong_sender_weak_signal`: `425`
- `weak_sender_strong_time_signal`: `838`

## Remaining Gaps

- no real post-prefilter Gmail production rows were introduced in this pass
- HTML/MIME flattening and long forwarding chains remain underrepresented
- chronological split is realistic but not perfectly quarter-balanced across all families

## Duplicate And Overlap Summary

- train exact duplicate ratio: 0.0000
- eval exact duplicate ratio: 0.0000
- shadow exact duplicate ratio: 0.0000
- train/eval overlap: 0
- train/shadow overlap: 0
- eval/shadow overlap: 0

## Training Outputs

- out of scope in this pass

## Runtime Outputs

- out of scope in this pass
