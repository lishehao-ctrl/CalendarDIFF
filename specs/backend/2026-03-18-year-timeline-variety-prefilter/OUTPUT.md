# Year Timeline Variety + Prefilter Evaluation Output

## Result

- Completed.
- Active full-sim bucket now contains `10368` messages (`576` core course, `9792` background noise).
- Archive created at `archive/generated/year_timeline_variety_prefilter_20260318`.
- Offline prefilter evaluation path added at `scripts/evaluate_local_email_prefilter.py`.

## Execution Plan

- Expand deterministic background stream volume and category variety without changing parser/prefilter behavior.
- Add prefilter-routing metadata to exported Gmail/full-sim samples.
- Archive prior generated year-timeline outputs before replacing active fixtures.
- Export refreshed email/ICS/mixed fixtures and add direct tests plus an offline prefilter-eval contract test.

## Changes Made

- Code / tooling:
  - `.gitignore`
  - `tools/datasets/year_timeline_background_stream.py`
  - `tools/datasets/year_timeline_full_sim.py`
  - `tools/datasets/export_year_timeline_fixtures.py`
  - `scripts/evaluate_local_email_prefilter.py`
  - `tests/test_year_timeline_background_stream.py`
  - `tests/test_year_timeline_fixture_export.py`
  - `tests/test_local_email_prefilter_evaluation.py`
- Generated / updated outputs:
  - `data/synthetic/year_timeline_demo/year_timeline_manifest.json`
  - `data/synthetic/year_timeline_demo/year_timeline_background_stream.json`
  - `data/synthetic/year_timeline_demo/year_timeline_full_sim_manifest.json`
  - `tests/fixtures/private/email_pool/library_catalog.json`
  - `tests/fixtures/private/email_pool/year_timeline_gmail/*`
  - `tests/fixtures/private/email_pool/year_timeline_full_sim/*`
  - `tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_smoke_96.json`
  - `tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_false_positive_bait_96.json`
  - `tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_academic_noise_96.json`
  - `tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_wrapper_heavy_96.json`
  - `tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_quarter_start_64.json`
  - `tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_finals_window_64.json`
  - `tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_mixed_regression_192.json`
  - existing year-timeline Gmail derived sets under `tests/fixtures/private/email_pool/derived_sets/*.json`
  - `tests/fixtures/private/ics_timeline/library_catalog.json`
  - `tests/fixtures/private/ics_timeline/derived_sets/*.json`
  - `tests/fixtures/private/ics_timeline/scenarios/year-timeline-*/*`
  - `tests/fixtures/private/year_timeline_mixed/library_catalog.json`
  - `tests/fixtures/private/year_timeline_mixed/derived_sets/year_timeline_cross_channel_lag_24.json`
- Dataset scale / mix:
  - Core monitored course mail: `576 / 10368` = `5.56%`
  - Academic non-target: `1728 / 10368` = `16.67%`
  - Wrapper clutter: `2592 / 10368` = `25.00%`
  - Unrelated general noise: `5472 / 10368` = `52.78%`
  - Background categories:
    - `academic_non_target=1728`
    - `lms_wrapper_noise=1028`
    - `newsletter=826`
    - `commerce=825`
    - `calendar_wrapper=738`
    - `jobs_and_careers=669`
    - `package_subscription=667`
    - `personal_finance=631`
    - `student_services=613`
    - `housing=588`
    - `account_security=498`
    - `clubs_and_events=494`
    - `campus_admin=487`
- Prefilter evaluation summary on full bucket with current `matches_gmail_source_filters()` behavior:
  - overall interception before LLM: `2798 / 10368` = `26.99%`
  - target-signal recall: `384 / 384` = `100%`
  - non-target interception: `2798 / 9984` = `28.02%`
  - heavy leak-through remains for `academic_non_target` and `lms_wrapper_noise`
- Realism improvement delivered:
  - stronger seasonal shifts across quarter start, project push, finals, and break-like commerce/social windows
  - more explicit unrelated categories and bait wording
  - prefilter labels now let us measure expected skip vs actual parse by family before LLM

## Validation

- `pytest -q tests/test_year_timeline_scenarios.py tests/test_year_timeline_background_stream.py tests/test_year_timeline_fixture_export.py tests/test_local_email_prefilter_evaluation.py`
- `python tools/datasets/year_timeline_scenarios.py --output data/synthetic/year_timeline_demo/year_timeline_manifest.json`
- `python tools/datasets/export_year_timeline_fixtures.py --manifest data/synthetic/year_timeline_demo/year_timeline_manifest.json --target all`
- `python scripts/process_local_email_pool.py --bucket year_timeline_gmail --derived-set year_timeline_alias_hard_48 --list-samples`
- `python scripts/evaluate_local_email_prefilter.py --bucket year_timeline_full_sim --format json`
- `python scripts/evaluate_local_email_prefilter.py --bucket year_timeline_full_sim --derived-set year_timeline_full_sim_false_positive_bait_96 --format json`
- `npm --prefix frontend run typecheck`
- `npm --prefix frontend run lint`
- `npm --prefix frontend run build`

## Risks / Remaining Issues

- Current Gmail source prefilter still leaks a large share of non-target academic/wrapper mail by design because this pass only measures the filter and does not retune it.
- Synthetic bodies are more varied now, but still cleaner and more template-shaped than real reply chains, forwarded blobs, and multilingual fragments.
- Sender ecology is still curated; it does not yet model highly personalized correspondents, odd aliases, or very long historical threads.
- Course-token world is still limited to the synthetic monitored catalog rather than a broader, messy campus inbox with many overlapping course formats.
