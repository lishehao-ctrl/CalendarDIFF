# Execution Output

## Changed Files

- `tools/datasets/year_timeline_scenarios.py`
- `tools/datasets/export_year_timeline_fixtures.py`
- `scripts/process_local_email_pool.py`
- `scripts/process_local_ics_timeline.py`
- `scripts/run_year_timeline_mixed_regression.py`
- `tests/test_year_timeline_scenarios.py`
- `tests/test_year_timeline_fixture_export.py`
- `tests/test_fake_source_provider_year_timeline_contract.py`
- `tests/test_year_timeline_mixed_regression_runner.py`
- `data/synthetic/year_timeline_demo/year_timeline_manifest.json`
- `tests/fixtures/private/email_pool/year_timeline_gmail/*`
- `tests/fixtures/private/email_pool/derived_sets/year_timeline_*`
- `tests/fixtures/private/ics_timeline/scenarios/year-timeline-*/*`
- `tests/fixtures/private/ics_timeline/derived_sets/year_timeline_*`
- `tests/fixtures/private/year_timeline_mixed/derived_sets/year_timeline_cross_channel_lag_24.json`
- `tests/fixtures/private/year_timeline_mixed/library_catalog.json`

## Validation Run

- `pytest -q tests/test_year_timeline_scenarios.py tests/test_year_timeline_fixture_export.py tests/test_fake_source_provider_year_timeline_contract.py tests/test_year_timeline_mixed_regression_runner.py`
  - result: `10 passed`
- `python tools/datasets/year_timeline_scenarios.py --output data/synthetic/year_timeline_demo/year_timeline_manifest.json`
  - result: manifest regenerated successfully
- `python tools/datasets/export_year_timeline_fixtures.py --manifest data/synthetic/year_timeline_demo/year_timeline_manifest.json --target all`
  - result: email, ics, and mixed fixtures regenerated successfully
- `python scripts/process_local_email_pool.py --bucket year_timeline_gmail --list-samples`
  - result: bucket listed successfully
- `python scripts/process_local_ics_timeline.py --derived-set year_timeline_smoke_16 --list-transitions`
  - result: derived transitions listed successfully
- `python scripts/run_year_timeline_mixed_regression.py --ics-derived-set year_timeline_smoke_16 --bundle-parallel 4 --email-parallel 12 --ics-parallel 12 --cache-mode enable --api-mode chat_completions`
  - result: bundle report materialized under `output/year-timeline-mixed-20260318-055738`

## What Improved

- Stable per-course realism is now generator-driven: each course carries `course_archetype`, `teaching_style`, and `channel_behavior`, and those profiles affect event cadence, sender role choice, alias drift, and lag patterns.
- Gmail sender roles are no longer generic staff mail. The dataset now mixes `professor`, `ta`, `course_staff_alias`, `canvas_wrapper`, `lab_coordinator`, and `department_admin`, with role-specific `from_header`, subject/body style, authority level, and junk profile.
- Quarter cadence is visibly week-shaped instead of uniform. Batches now encode setup, early ramp, first pressure, project push, late crunch, and finals/rollover behavior, and summer runs with tighter lead times and lower bureaucracy.
- Gmail vs Canvas/ICS are no longer assumed to sync in the same batch. The generator now encodes `same_batch`, `email_first`, `canvas_first`, `canvas_plus_1_batch`, `email_plus_1_batch`, and `calendar_only`.
- ICS realism is stronger: structured deltas now include due-date shifts, due-time-only shifts, alias-title drift, exam schedule changes, and removals, with transition metadata exported into scenario manifests.
- Junk content is materially heavier but still controlled. Signals are wrapped in greetings, FAQ text, rubric unchanged language, submission notes, office-hours references, staffing/admin blocks, and Canvas wrapper text without turning the smoke path into nonsense.
- New derived sets were added for professor/TA authority conflict, Canvas wrapper mail, junk-heavy Gmail, calendar-first ICS, email-first ICS, and mixed cross-channel lag bundles.

## Remaining Gaps

- The professor/TA realism is still synthetic-name based rather than tied to real institutional rosters.
- `email_plus_1_batch` is encoded as dataset metadata and bundle selection logic, but the pipeline still does not run a true delayed follow-up mail emission engine across batches.
- Canvas wrapper text is much noisier now, but it is still cleaner and more regular than real LMS HTML/email wrappers.
- The mixed regression runner currently materializes deterministic bundles and reports; it does not execute the full historical live-model workflow from this repo.
