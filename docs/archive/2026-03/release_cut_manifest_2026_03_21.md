# Release Cut Manifest

## Candidate

- branch: `codex/release-cut-20260321`
- base: `6273f39`
- purpose: production launch candidate

## Included

This release candidate intentionally includes the current working-tree state for:

- runtime/apply/runtime-state refactors that are already required by the running local backend
- new product-lane backend contracts:
  - `workspace_posture`
  - `decision_support`
  - `source_product_phase`
  - `source_recovery`
- current UI integration for:
  - `Overview`
  - `Initial Review`
  - `Changes`
  - `Sources`
- timezone search UX improvements
- current OpenAPI snapshot

## Explicit exclusions

These artifacts were intentionally excluded from the release-cut workspace:

- `training/gmail_secondary_filter/train_distilbert.py`
- `scripts/evaluate_full_sim_prefilter_bert.py`
- `scripts/estimate_bert_enable_threshold.py`
- `scripts/compare_real_gmail_filter_strategies.py`
- `tests/test_gmail_second_filter_policy.py`

## Notes

- BERT / secondary-filter experimentation remains out of release scope.
- Runtime support code related to secondary filtering may still exist in-tree, but production must continue running with the secondary filter disabled.
- Secrets and local env files were not copied into this release candidate.
